"""Parse markdown files → populate SQLite (nodes, edges, tags, aliases, chunks, FTS5, chunks_vec).

Two-pass algorithm:
  Pass 1: Establish all nodes (parse files, upsert into DB, build FTS5)
  Pass 2: Extract edges (sources, related, wikilinks) + chunk + embed
"""

import hashlib
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config
from .db import get_connection, init_schema
from .embeddings import EmbeddingProvider, get_provider, content_hash as compute_content_hash


# ── Frontmatter parsing ───────────────────────────────────────────────

def parse_markdown(file_path: Path) -> tuple[dict, str]:
    """Parse a markdown file into (frontmatter_dict, body_text).

    Returns ({}, body) if no frontmatter found.
    """
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end_idx = text.find("---", 3)
    if end_idx == -1:
        return {}, text

    fm_text = text[3:end_idx].strip()
    body = text[end_idx + 3:].strip()

    try:
        fm = yaml.safe_load(fm_text)
        if not isinstance(fm, dict):
            fm = {}
    except yaml.YAMLError:
        fm = {}

    return fm, body


def file_md5(file_path: Path) -> str:
    """Compute MD5 hash of a file's contents."""
    return hashlib.md5(file_path.read_bytes()).hexdigest()


def slug_from_path(file_path: Path, wiki_dir: Path) -> str:
    """Derive a node ID slug from a wiki file path.

    wiki/agent-memory.md → agent-memory
    wiki/concepts/ai-coding-agents.md → ai-coding-agents  (legacy subdirs)
    """
    return file_path.stem


# ── Wikilink extraction ───────────────────────────────────────────────

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def extract_wikilinks(body: str) -> list[str]:
    """Extract all [[wikilink]] targets from body text.

    Handles [[target|display]] by extracting only the target part.
    """
    return WIKILINK_RE.findall(body)


def resolve_wikilink(target: str, resolution_table: dict[str, list[str]]) -> str | None:
    """Resolve a wikilink target to a node ID using the resolution table.

    Tries: exact match, alias match, case-insensitive.
    Returns None if unresolved.
    """
    # Normalize: strip .md, strip wiki/ prefix, strip leading/trailing whitespace
    target = target.strip()
    if target.startswith("wiki/"):
        target = target[5:]
    if target.endswith(".md"):
        target = target[:-3]

    # Skip raw file references
    if target.startswith(".raw/") or target.startswith("raw/"):
        return None

    # Exact match (flat slug or alias)
    if target in resolution_table:
        ids = resolution_table[target]
        return ids[0] if len(ids) == 1 else None  # ambiguous → None

    # Try lowercase
    target_lower = target.lower()
    for key, ids in resolution_table.items():
        if key.lower() == target_lower:
            return ids[0] if len(ids) == 1 else None

    # Legacy: strip path prefix for old-style [[concepts/agent-memory]] links
    if "/" in target:
        basename = target.rsplit("/", 1)[-1]
        if basename in resolution_table:
            ids = resolution_table[basename]
            return ids[0] if len(ids) == 1 else None
        for key, ids in resolution_table.items():
            if key.lower() == basename.lower():
                return ids[0] if len(ids) == 1 else None

    return None


# ── Chunking ──────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def chunk_body(
    body: str,
    title: str = "",
    tags: list[str] | None = None,
    target_tokens: int = 0,
    overlap_tokens: int = 0,
) -> list[dict]:
    """Split body into chunks for embedding.

    Returns list of {text, chunk_index, start_line, end_line}.
    Each chunk gets a title+tags metadata prefix prepended.
    """
    target_tokens = target_tokens or config.CHUNK_TARGET_TOKENS
    overlap_tokens = overlap_tokens or config.CHUNK_OVERLAP_TOKENS
    tags = tags or []

    # Build metadata prefix
    prefix_parts = []
    if title:
        prefix_parts.append(f"Title: {title}")
    if tags:
        prefix_parts.append(f"Tags: {' '.join(tags)}")
    prefix = "\n".join(prefix_parts) + "\n\n" if prefix_parts else ""

    if not body.strip():
        return [{"text": prefix.strip(), "chunk_index": 0, "start_line": 1, "end_line": 1}]

    # Split on ## headings first
    sections: list[tuple[int, str]] = []
    lines = body.split("\n")
    current_start = 0
    current_lines: list[str] = []

    for i, line in enumerate(lines):
        if line.startswith("## ") and current_lines:
            sections.append((current_start, "\n".join(current_lines)))
            current_start = i
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_start, "\n".join(current_lines)))

    # Further split sections that exceed target tokens
    raw_chunks: list[tuple[int, int, str]] = []
    for start_line, section_text in sections:
        section_lines = section_text.split("\n")
        if _estimate_tokens(section_text) <= target_tokens:
            end_line = start_line + len(section_lines) - 1
            raw_chunks.append((start_line, end_line, section_text))
        else:
            # Split on paragraph boundaries
            para_start = 0
            para_lines: list[str] = []
            para_start_line = start_line

            for j, line in enumerate(section_lines):
                para_lines.append(line)
                is_para_break = (line.strip() == "" and j > 0)
                is_last = (j == len(section_lines) - 1)

                if (is_para_break or is_last) and _estimate_tokens("\n".join(para_lines)) >= target_tokens:
                    raw_chunks.append((para_start_line, start_line + j, "\n".join(para_lines)))
                    para_start_line = start_line + j + 1
                    para_lines = []

            if para_lines:
                raw_chunks.append((para_start_line, start_line + len(section_lines) - 1, "\n".join(para_lines)))

    # Build final chunks with prefix and overlap
    chunks = []
    for idx, (start, end, text) in enumerate(raw_chunks):
        chunk_text = prefix + text.strip()
        chunks.append({
            "text": chunk_text,
            "chunk_index": idx,
            "start_line": start + 1,  # 1-indexed
            "end_line": end + 1,
        })

    # Handle empty body edge case
    if not chunks:
        chunks.append({"text": prefix.strip(), "chunk_index": 0, "start_line": 1, "end_line": 1})

    return chunks


# ── Main indexer ──────────────────────────────────────────────────────

class Indexer:
    """Two-pass indexer: markdown files → SQLite."""

    def __init__(
        self,
        conn,
        wiki_dir: Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        dry_run: bool = False,
    ):
        self.conn = conn
        self.wiki_dir = wiki_dir or config.WIKI_DIR
        self.provider = embedding_provider
        self.dry_run = dry_run
        self._resolution_table: dict[str, list[str]] = {}
        self.stats = {
            "files_scanned": 0,
            "files_indexed": 0,
            "files_skipped": 0,
            "files_deleted": 0,
            "chunks_created": 0,
            "chunks_embedded": 0,
            "errors": [],
        }

    def rebuild(self, force: bool = False) -> dict:
        """Run the full two-pass index build.

        Args:
            force: If True, re-index all files regardless of hash.

        Returns:
            Stats dict with counts of what happened.
        """
        init_schema(self.conn)

        all_files = self._discover_files()
        self.stats["files_scanned"] = len(all_files)

        # Pass 1: establish nodes
        changed_ids = self._pass1_nodes(all_files, force=force)

        # Build resolution table (between passes)
        self._build_resolution_table()

        # Pass 2: edges + chunks + embeddings
        self._pass2_edges_and_chunks(changed_ids)

        # Finalize: embed, reconcile, clean orphans
        self._finalize_embeddings()
        self._reconcile_orphan_chunks()
        self._clean_orphan_nodes(all_files)

        return self.stats

    def index_single(self, file_path: Path) -> str | None:
        """Index (or re-index) a single file. Returns the node ID or None on error."""
        init_schema(self.conn)

        if not file_path.exists():
            return None

        node_id = slug_from_path(file_path, self.wiki_dir)
        fm, body = parse_markdown(file_path)
        if not fm.get("title"):
            return None

        fhash = file_md5(file_path)
        rel_path = str(file_path.relative_to(self.wiki_dir.parent))

        self._upsert_node(node_id, rel_path, fm, body, fhash)

        # Build resolution table for edge extraction
        self._build_resolution_table()
        self._extract_edges(node_id, fm, body)
        self._chunk_and_prepare(node_id, fm, body)
        self._finalize_embeddings()

        # Update hash after successful embedding
        if not self.dry_run:
            self.conn.execute("UPDATE nodes SET file_hash = ? WHERE id = ?", (fhash, node_id))
            self.conn.commit()

        return node_id

    # ── Pass 1 ─────────────────────────────────────────────────────

    def _discover_files(self) -> list[Path]:
        """Find all .md files in wiki/ excluding skip list."""
        files = []
        for p in sorted(self.wiki_dir.rglob("*.md")):
            if p.name in config.SKIP_FILES:
                continue
            # Skip hidden directories
            if any(part.startswith(".") for part in p.relative_to(self.wiki_dir).parts):
                continue
            files.append(p)
        return files

    def _pass1_nodes(self, files: list[Path], force: bool = False) -> list[str]:
        """Parse files, upsert nodes + FTS5. Returns list of changed node IDs."""
        changed_ids = []

        for file_path in files:
            node_id = slug_from_path(file_path, self.wiki_dir)
            fhash = file_md5(file_path)

            # Check if unchanged
            if not force:
                existing = self.conn.execute(
                    "SELECT file_hash FROM nodes WHERE id = ?", (node_id,)
                ).fetchone()
                if existing and existing["file_hash"] == fhash:
                    self.stats["files_skipped"] += 1
                    continue

            fm, body = parse_markdown(file_path)
            if not fm.get("title"):
                self.stats["errors"].append(f"{file_path.name}: no title in frontmatter")
                continue

            rel_path = str(file_path.relative_to(self.wiki_dir.parent))

            if self.dry_run:
                changed_ids.append(node_id)
                self.stats["files_indexed"] += 1
                continue

            self._upsert_node(node_id, rel_path, fm, body, new_hash=None)
            # Store the real hash temporarily for later update after embedding
            self.conn.execute(
                "UPDATE nodes SET indexed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), node_id),
            )
            # We'll set file_hash in finalize, after embedding succeeds
            self._pending_hashes = getattr(self, "_pending_hashes", {})
            self._pending_hashes[node_id] = fhash

            changed_ids.append(node_id)
            self.stats["files_indexed"] += 1

        if not self.dry_run:
            self.conn.commit()

        return changed_ids

    def _upsert_node(self, node_id: str, rel_path: str, fm: dict, body: str, new_hash: str | None) -> None:
        """Insert or update a node + its FTS5/tags/aliases entries atomically."""
        from .markdown import normalize_alias

        title = str(fm.get("title", ""))
        origin = str(fm.get("origin") or fm.get("type", "meta"))
        status = str(fm.get("status", "seed"))
        created_at = str(fm.get("created_at") or fm.get("created", ""))
        updated_at = str(fm.get("updated_at") or fm.get("updated", created_at))
        tags = fm.get("tags") or []
        aliases = fm.get("aliases") or []

        self.conn.execute("""
            INSERT INTO nodes (id, file_path, title, origin, status, created_at, updated_at,
                               sentiment, complexity, confidence,
                               ingested_via, briefing_date, url, author,
                               body, word_count, file_hash, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                file_path = excluded.file_path,
                title = excluded.title,
                origin = excluded.origin,
                status = excluded.status,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                sentiment = excluded.sentiment,
                complexity = excluded.complexity,
                confidence = excluded.confidence,
                ingested_via = excluded.ingested_via,
                briefing_date = excluded.briefing_date,
                url = excluded.url,
                author = excluded.author,
                body = excluded.body,
                word_count = excluded.word_count,
                file_hash = excluded.file_hash,
                indexed_at = excluded.indexed_at
        """, (
            node_id, rel_path, title, origin, status, created_at, updated_at,
            fm.get("sentiment"),
            fm.get("complexity"), fm.get("confidence"),
            fm.get("ingested_via"), str(fm.get("briefing_date", "")) or None,
            fm.get("url") or fm.get("source_url"), fm.get("author"),
            body, len(body.split()),
            new_hash,
            datetime.now(timezone.utc).isoformat(),
        ))

        # Tags
        self.conn.execute("DELETE FROM tags WHERE node_id = ?", (node_id,))
        for tag in tags:
            self.conn.execute(
                "INSERT OR IGNORE INTO tags (node_id, tag) VALUES (?, ?)",
                (node_id, str(tag)),
            )

        # Aliases — new schema with alias_norm PK
        self.conn.execute("DELETE FROM aliases WHERE node_id = ?", (node_id,))
        now = datetime.now(timezone.utc).isoformat()
        for alias in aliases:
            alias_str = str(alias)
            anorm = normalize_alias(alias_str)
            # Check for conflicts with other nodes
            existing = self.conn.execute(
                "SELECT node_id FROM aliases WHERE alias_norm = ?", (anorm,)
            ).fetchone()
            if existing and existing["node_id"] != node_id:
                # Conflict — skip this alias, log warning
                self.stats.get("errors", []).append(
                    f"Alias conflict: '{alias_str}' (norm: '{anorm}') claimed by {existing['node_id']}, skipping for {node_id}"
                ) if hasattr(self, 'stats') else None
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO aliases (alias_norm, alias, node_id, alias_kind, created_at) VALUES (?, ?, ?, ?, ?)",
                (anorm, alias_str, node_id, "old_path" if "/" in alias_str else "title", now),
            )
        # Also add title as alias
        title_norm = normalize_alias(title)
        existing = self.conn.execute(
            "SELECT node_id FROM aliases WHERE alias_norm = ?", (title_norm,)
        ).fetchone()
        if not existing or existing["node_id"] == node_id:
            self.conn.execute(
                "INSERT OR REPLACE INTO aliases (alias_norm, alias, node_id, alias_kind, created_at) VALUES (?, ?, ?, ?, ?)",
                (title_norm, title, node_id, "title", now),
            )

        # FTS5 — explicit management (no triggers)
        tags_text = " ".join(str(t) for t in tags)
        self.conn.execute("DELETE FROM nodes_fts WHERE node_id = ?", (node_id,))
        self.conn.execute(
            "INSERT INTO nodes_fts (node_id, title, body, tags_text) VALUES (?, ?, ?, ?)",
            (node_id, title, body, tags_text),
        )

    # ── Between passes ─────────────────────────────────────────────

    def _build_resolution_table(self) -> None:
        """Build in-memory dict for O(1) wikilink resolution."""
        self._resolution_table = {}

        # Node IDs (flat slugs)
        for row in self.conn.execute("SELECT id FROM nodes"):
            nid = row["id"]
            self._resolution_table.setdefault(nid, []).append(nid)

        # Aliases (normalized key → node_id)
        for row in self.conn.execute("SELECT alias_norm, alias, node_id FROM aliases"):
            anorm = row["alias_norm"]
            alias_lower = row["alias"].lower()
            self._resolution_table.setdefault(anorm, []).append(row["node_id"])
            # Also add the raw alias (lowercased) for case-insensitive matching
            if alias_lower != anorm:
                self._resolution_table.setdefault(alias_lower, []).append(row["node_id"])

    # ── Pass 2 ─────────────────────────────────────────────────────

    def _pass2_edges_and_chunks(self, changed_ids: list[str]) -> None:
        """Extract edges and create chunks for changed nodes."""
        if self.dry_run:
            return

        for node_id in changed_ids:
            row = self.conn.execute(
                "SELECT body, title, origin FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if not row:
                continue

            fm_row = self.conn.execute(
                "SELECT * FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            # Reconstruct frontmatter dict from DB columns
            fm = {
                "sources": [],
                "related": [],
                "tags": [r["tag"] for r in self.conn.execute("SELECT tag FROM tags WHERE node_id = ?", (node_id,))],
            }
            # Get sources and related from the file itself (need to re-parse)
            file_path = self.wiki_dir.parent / fm_row["file_path"]
            if file_path.exists():
                parsed_fm, _ = parse_markdown(file_path)
                fm["sources"] = parsed_fm.get("sources") or []
                fm["related"] = parsed_fm.get("related") or []

            self._extract_edges(node_id, fm, row["body"])
            self._chunk_and_prepare(node_id, fm, row["body"])

        self.conn.commit()

    def _extract_edges(self, node_id: str, fm: dict, body: str) -> None:
        """Extract and store edges from frontmatter and body wikilinks.

        Edge types are singular: 'source', 'related', 'link'.
        raw_sources are provenance pointers — NOT extracted as graph edges.
        """
        # Clear existing edges for this node
        self.conn.execute("DELETE FROM edges WHERE from_id = ?", (node_id,))

        # Source edges (from frontmatter sources: [...])
        for source_ref in (fm.get("sources") or []):
            target = self._strip_wikilink(str(source_ref))
            # Skip .raw/ references — these are provenance, not graph edges
            if target.startswith(".raw/") or target.startswith("raw/"):
                continue
            resolved = resolve_wikilink(target, self._resolution_table)
            to_id = resolved or target
            self.conn.execute(
                "INSERT OR IGNORE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'source')",
                (node_id, to_id),
            )

        # Related edges
        for related_ref in (fm.get("related") or []):
            target = self._strip_wikilink(str(related_ref))
            resolved = resolve_wikilink(target, self._resolution_table)
            to_id = resolved or target
            self.conn.execute(
                "INSERT OR IGNORE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'related')",
                (node_id, to_id),
            )

        # Link edges from body wikilinks
        wikilinks = extract_wikilinks(body)
        for target in wikilinks:
            resolved = resolve_wikilink(target, self._resolution_table)
            if resolved and resolved != node_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'link')",
                    (node_id, resolved),
                )

    @staticmethod
    def _strip_wikilink(ref: str) -> str:
        """Strip [[...]] wrapper from a wikilink reference."""
        ref = ref.strip()
        if ref.startswith("[[") and ref.endswith("]]"):
            ref = ref[2:-2]
        # Handle display text: [[target|display]]
        if "|" in ref:
            ref = ref.split("|")[0]
        return ref.strip()

    def _chunk_and_prepare(self, node_id: str, fm: dict, body: str) -> None:
        """Chunk the body and prepare for embedding."""
        tags = fm.get("tags") or []
        title_row = self.conn.execute("SELECT title FROM nodes WHERE id = ?", (node_id,)).fetchone()
        title = title_row["title"] if title_row else ""

        chunks = chunk_body(body, title=title, tags=tags)

        # Clear old chunks (cascade trigger handles chunks_vec)
        self.conn.execute("DELETE FROM chunks WHERE node_id = ?", (node_id,))

        for chunk in chunks:
            chash = compute_content_hash(chunk["text"])
            self.conn.execute(
                "INSERT INTO chunks (node_id, chunk_index, text, start_line, end_line, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (node_id, chunk["chunk_index"], chunk["text"], chunk["start_line"], chunk["end_line"], chash),
            )
            self.stats["chunks_created"] += 1

    # ── Finalize ───────────────────────────────────────────────────

    def _finalize_embeddings(self) -> None:
        """Batch-embed all chunks that don't have vectors yet."""
        if self.dry_run or self.provider is None:
            return

        # Find chunks without vectors
        rows = self.conn.execute("""
            SELECT c.chunk_id, c.node_id, c.text, c.content_hash
            FROM chunks c
            LEFT JOIN chunks_vec cv ON c.chunk_id = cv.rowid
            WHERE cv.rowid IS NULL
        """).fetchall()

        if not rows:
            return

        # Batch embed
        batch_size = config.VOYAGE_BATCH_SIZE
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            texts = [r["text"] for r in batch]

            try:
                embeddings = self.provider.embed(texts, input_type="document")
            except Exception as e:
                self.stats["errors"].append(f"Embedding batch {i // batch_size}: {e}")
                continue

            for row, emb in zip(batch, embeddings):
                emb_bytes = struct.pack(f"{len(emb)}f", *emb)
                self.conn.execute(
                    "INSERT OR REPLACE INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                    (row["chunk_id"], emb_bytes),
                )
                self.stats["chunks_embedded"] += 1

        # Update file_hash for successfully embedded nodes
        pending = getattr(self, "_pending_hashes", {})
        for node_id, fhash in pending.items():
            # Check if all chunks for this node have vectors
            orphan = self.conn.execute("""
                SELECT COUNT(*) as cnt FROM chunks c
                LEFT JOIN chunks_vec cv ON c.chunk_id = cv.rowid
                WHERE c.node_id = ? AND cv.rowid IS NULL
            """, (node_id,)).fetchone()
            if orphan["cnt"] == 0:
                self.conn.execute("UPDATE nodes SET file_hash = ? WHERE id = ?", (fhash, node_id))

        self.conn.commit()
        self._pending_hashes = {}

    def _reconcile_orphan_chunks(self) -> None:
        """Safety net: find chunks without vectors and mark their nodes for re-embed."""
        if self.dry_run or self.provider is None:
            return

        orphans = self.conn.execute("""
            SELECT DISTINCT c.node_id FROM chunks c
            LEFT JOIN chunks_vec cv ON c.chunk_id = cv.rowid
            WHERE cv.rowid IS NULL
        """).fetchall()

        self.stats["orphan_chunks"] = len(orphans)

    def _clean_orphan_nodes(self, active_files: list[Path]) -> None:
        """Delete nodes in DB that no longer have files on disk."""
        if self.dry_run:
            return

        active_paths = {
            str(f.relative_to(self.wiki_dir.parent))
            for f in active_files
        }

        db_paths = {
            row["file_path"]
            for row in self.conn.execute("SELECT file_path FROM nodes")
        }

        orphan_paths = db_paths - active_paths
        for op in orphan_paths:
            node_id = self.conn.execute(
                "SELECT id FROM nodes WHERE file_path = ?", (op,)
            ).fetchone()
            if node_id:
                # FTS5 first (no cascade)
                self.conn.execute("DELETE FROM nodes_fts WHERE node_id = ?", (node_id["id"],))
                # Then node (cascade handles edges/tags/chunks → chunks_ad trigger handles chunks_vec)
                self.conn.execute("DELETE FROM nodes WHERE file_path = ?", (op,))
                self.stats["files_deleted"] += 1

        if orphan_paths:
            self.conn.commit()
