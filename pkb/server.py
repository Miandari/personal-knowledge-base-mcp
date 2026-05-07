"""FastMCP server: kb_find, kb_save, kb_status."""

import os
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import config
from .db import get_connection, init_schema
from .embeddings import get_provider
from .indexer import Indexer, parse_markdown, file_md5, slug_from_path
from .models import NodeSummary, SearchResult, NodeDetail, StatusResult
from .search import (
    hybrid_search, fts_search, get_node, get_node_summary,
    list_nodes, get_status,
)

mcp = FastMCP("pkb", instructions="""\
Personal knowledge base tools. These access the user's PERSONAL wiki — \
a curated collection of notes, articles, papers, and compiled pages. \
NOT the public internet.

Use these tools when the user asks about their personal notes, KB, wiki, \
or vault. Trigger phrases: "in my KB", "in my notes", "check my vault", \
"what do I know about", "query:", "kb:". For general knowledge questions, \
prefer web search or your own training data.

Three tools: kb_find (read), kb_save (write), kb_status (health check).""")

_KB_TOKEN = os.getenv("KB_MCP_TOKEN")

# --- Tool description constants ---

_FIND_DESC = """\
Personal KB tool. Find and retrieve pages from the user's personal wiki.

Modes (determined by parameters):
- Search: kb_find(query="agent memory") — hybrid FTS5 + vector search.
  Returns ranked results with scores and snippets. Use "hybrid" mode
  (default) for best quality; "bm25" for exact keyword matching.
- Get page: kb_find(id="agent-memory") — full page content + metadata +
  graph edges (sources, sourced_by, related, wikilinks).
- Browse: kb_find(origin="paper") or kb_find(tag="rag") — filtered listing
  sorted by the chosen field.

Results are ranked by Reciprocal Rank Fusion score. Only ordering matters —
do not interpret raw score values as similarity percentages.

DO NOT use this for general knowledge questions — use web search instead.
DO NOT guess node IDs — search first to find valid IDs."""

_SAVE_DESC = """\
Personal KB tool. Create, update, or reindex pages in the user's personal
wiki. Automatically reindexes after every write.

Modes (determined by parameters):
- Create new page: kb_save(title="...", origin="note", body="...")
- Update metadata: kb_save(id="...", tags=["..."], related=["..."])
- Update a section: kb_save(id="...", section="Summary", body="new content")
- Replace body: kb_save(id="...", body="new full body")
- Reindex after external edit: kb_save(id="...")

The `origin` field specifies provenance: webpage, paper, conversation,
note, book, transcript, meta.

Use `sources` for pages this was built FROM (creates source edges).
Use `related` for pages this is RELEVANT TO (creates related edges).
Wikilinks are pathless: use "agent-memory" not "concepts/agent-memory".

On create, returns `suggested_related` (semantically similar pages) and
`suggested_tags` (common tags from similar pages) to help link new content.

Does NOT fetch URLs — pass content directly in the body parameter."""

_STATUS_DESC = """\
Personal KB tool. Health check for the user's personal knowledge base index.
Returns node count, edge count, chunk count, embedding coverage percentage,
stale page count, and orphan chunk count.

Use this to verify the index is healthy before searching. If embedding
coverage is below 100%, run `pkb rebuild` to fix it."""


_NO_VAULT_MSG = (
    "No vault found. To get started:\n\n"
    "1. Run: pkb init ~/my-knowledge-base\n"
    "2. Set your VOYAGE_API_KEY in ~/my-knowledge-base/.env\n"
    "3. Run: pkb --vault ~/my-knowledge-base rebuild\n"
    "4. Update your MCP config:\n"
    '   {"command": "pkb", "args": ["--vault", "~/my-knowledge-base", "server"]}\n'
    "5. Restart your MCP client."
)


def _check_vault():
    """Check if a vault exists. Returns error dict if not, None if OK."""
    if not config.WIKI_DIR.is_dir():
        return {"error": _NO_VAULT_MSG}
    return None


class VaultNotFoundError(Exception):
    pass


def _get_conn():
    """Get a DB connection, initializing schema if needed."""
    if not config.WIKI_DIR.is_dir():
        raise VaultNotFoundError(_NO_VAULT_MSG)
    conn = get_connection()
    init_schema(conn)
    return conn


def _get_provider(conn):
    """Get the embedding provider with caching."""
    provider_name = os.getenv("KB_EMBEDDING_PROVIDER", config.EMBEDDING_PROVIDER)
    return get_provider(provider_name, conn=conn)


def _reindex_file(conn, fp: Path) -> str | None:
    """Reindex a single file. Returns node_id or None."""
    # Flush detection: wait for write to complete
    for _ in range(5):
        mtime1, size1 = fp.stat().st_mtime, fp.stat().st_size
        time.sleep(0.05)
        mtime2, size2 = fp.stat().st_mtime, fp.stat().st_size
        if mtime1 == mtime2 and size1 == size2 and size1 > 0:
            break

    provider = _get_provider(conn)
    indexer = Indexer(conn, embedding_provider=provider)
    return indexer.index_single(fp)


def _resolve_file_path(conn, node_id: str) -> Path | None:
    """Resolve a node_id to its file path."""
    row = conn.execute("SELECT file_path FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not row:
        return None
    fp = Path(row["file_path"])
    if not fp.is_absolute():
        fp = config.VAULT_ROOT / fp
    return fp


# --- MCP Tools ---

@mcp.tool(description=_FIND_DESC)
def kb_find(
    query: str = "",
    id: str = "",
    origin: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    sentiment: str | None = None,
    mode: str = "hybrid",
    sort: str = "updated_at",
    limit: int = 10,
) -> dict | list[dict] | None:
    """Find and retrieve pages from the personal wiki."""
    conn = _get_conn()
    try:
        # Get by ID
        if id:
            detail = get_node(conn, id)
            return detail.model_dump() if detail else None

        # Browse by filters (when no query given)
        if not query and (origin or tag or status):
            nodes = list_nodes(conn, origin_filter=origin, tag_filter=tag,
                              status_filter=status, sort=sort, limit=limit)
            return [n.model_dump() for n in nodes]

        # Search by query (handles empty string gracefully)
        if query or not (origin or tag or status):
            filters = {}
            if origin:
                filters["origin"] = origin
            if sentiment:
                filters["sentiment"] = sentiment

            if mode == "bm25":
                results = fts_search(conn, query, limit=limit, filters=filters)
            else:
                provider = _get_provider(conn)
                results = hybrid_search(conn, query, limit=limit, filters=filters, embedding_provider=provider)
            return [r.model_dump() for r in results]

        return {"error": "Provide query, id, or filters"}
    finally:
        conn.close()


@mcp.tool(description=_SAVE_DESC)
def kb_save(
    title: str = "",
    id: str = "",
    origin: str = "",
    body: str = "",
    section: str = "",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    related: list[str] | None = None,
    source_url: str = "",
    sentiment: str = "",
    status: str = "",
    ingested_via: str = "manual",
) -> dict:
    """Create, update, or reindex pages in the personal wiki."""
    # --- Create new page ---
    if not id and title:
        return _create_page(
            title=title, origin=origin, body=body, source_url=source_url,
            tags=tags, sources=sources, related=related,
            sentiment=sentiment, ingested_via=ingested_via,
        )

    # --- Update or reindex existing page ---
    if id:
        return _update_page(
            node_id=id, body=body, section=section,
            tags=tags, sources=sources, related=related,
            source_url=source_url, sentiment=sentiment, status=status,
        )

    return {"error": "Provide 'id' to update, or 'title' + 'origin' + 'body' to create."}


@mcp.tool(description=_STATUS_DESC)
def kb_status() -> dict:
    """Index health check."""
    conn = _get_conn()
    try:
        result = get_status(conn)
        return result.model_dump()
    finally:
        conn.close()


# --- Internal helpers ---

def _create_page(
    title: str,
    origin: str,
    body: str,
    source_url: str = "",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    related: list[str] | None = None,
    sentiment: str = "",
    ingested_via: str = "manual",
) -> dict:
    """Create a new wiki page, index it, and return summary with suggestions."""
    tags = tags or []
    sources = sources or []
    related = related or []

    if not origin:
        return {"error": "origin is required for new pages"}

    slug = _slugify(title)
    file_path = config.WIKI_DIR / f"{slug}.md"

    if file_path.exists():
        return {"error": f"File already exists: {file_path.relative_to(config.VAULT_ROOT)}. Use kb_save(id=\"{slug}\", ...) to update."}

    # Check alias conflicts
    from .markdown import normalize_alias
    conn_check = _get_conn()
    try:
        slug_norm = normalize_alias(slug)
        existing_alias = conn_check.execute(
            "SELECT node_id FROM aliases WHERE alias_norm = ?", (slug_norm,)
        ).fetchone()
        if existing_alias:
            return {"error": f"Slug '{slug}' conflicts with alias for node '{existing_alias['node_id']}'. Choose a different title."}
    finally:
        conn_check.close()

    # Generate frontmatter
    today = date.today().isoformat()
    fm_lines = [
        "---",
        f'title: "{title}"',
        f"origin: {origin}",
        "status: seed",
    ]
    if ingested_via:
        fm_lines.append(f"ingested_via: {ingested_via}")
    if tags:
        fm_lines.append("tags:")
        for t in tags:
            fm_lines.append(f"  - {t}")
    if source_url:
        fm_lines.append(f'url: "{source_url}"')
    if sentiment:
        fm_lines.append(f"sentiment: {sentiment}")
    if sources:
        fm_lines.append("sources:")
        for s in sources:
            fm_lines.append(f'  - "[[{s}]]"')
    if related:
        fm_lines.append("related:")
        for r in related:
            fm_lines.append(f'  - "[[{r}]]"')
    else:
        fm_lines.append("related: []")
    fm_lines.append(f"created_at: {today}")
    fm_lines.append(f"updated_at: {today}")
    fm_lines.append("---")

    full_content = "\n".join(fm_lines) + f"\n\n# {title}\n\n" + body

    # Write file
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(full_content, encoding="utf-8")

    # Index immediately
    conn = _get_conn()
    try:
        provider = _get_provider(conn)
        indexer = Indexer(conn, embedding_provider=provider)
        node_id = indexer.index_single(file_path)

        if node_id:
            summary = get_node_summary(conn, node_id)
            result = summary.model_dump() if summary else {"id": node_id, "file_path": str(file_path)}

            # Auto-suggest related pages
            meta_pages = {"index", "log", "hot"}
            declared_set = set(related) | set(sources)
            try:
                suggestions = hybrid_search(conn, body[:2000], limit=5, embedding_provider=provider)
                similar_pages = [
                    s for s in suggestions
                    if s.node_id != node_id
                    and s.node_id not in meta_pages
                    and s.node_id not in declared_set
                ][:3]
                result["suggested_related"] = [
                    {"id": s.node_id, "title": s.title}
                    for s in similar_pages
                ]

                # Auto-suggest tags from similar pages
                tag_counter: Counter = Counter()
                for s in similar_pages:
                    page_tags = conn.execute(
                        "SELECT tag FROM tags WHERE node_id = ?", (s.node_id,)
                    ).fetchall()
                    for row in page_tags:
                        if row["tag"] not in tags:
                            tag_counter[row["tag"]] += 1
                result["suggested_tags"] = [t for t, _ in tag_counter.most_common(5)]

            except Exception:
                result["suggested_related"] = []
                result["suggested_tags"] = []

            return result
        return {"error": "Indexing failed"}
    finally:
        conn.close()


def _update_page(
    node_id: str,
    body: str = "",
    section: str = "",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    related: list[str] | None = None,
    source_url: str = "",
    sentiment: str = "",
    status: str = "",
) -> dict:
    """Update an existing page (section, body, frontmatter, or reindex-only)."""
    conn = _get_conn()
    try:
        fp = _resolve_file_path(conn, node_id)
        if fp is None:
            return {"error": f"Node not found: {node_id}"}
        if not fp.exists():
            return {"error": f"File not found: {fp}"}

        has_body = bool(body)
        has_metadata = any([tags, sources, related, source_url, sentiment, status])

        if has_body and section:
            # Section update
            from .markdown import replace_or_insert_section
            content = fp.read_text(encoding="utf-8")
            content = replace_or_insert_section(content, section, body)
            fp.write_text(content, encoding="utf-8")

        elif has_body:
            # Full body replacement (preserve frontmatter)
            content = fp.read_text(encoding="utf-8")
            fm, _ = parse_markdown(fp)
            # Reconstruct: keep everything up to end of frontmatter, replace body
            fm_match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if fm_match:
                fm_text = fm_match.group(0)
            else:
                fm_text = ""
            fp.write_text(fm_text + "\n" + body, encoding="utf-8")

        elif has_metadata:
            # Frontmatter-only update
            content = fp.read_text(encoding="utf-8")
            content = _apply_frontmatter_updates(
                content, tags=tags, sources=sources, related=related,
                source_url=source_url, sentiment=sentiment, status=status,
            )
            fp.write_text(content, encoding="utf-8")

        # Reindex (always — covers reindex-only mode too)
        result_id = _reindex_file(conn, fp)
        if result_id:
            summary = get_node_summary(conn, result_id)
            return summary.model_dump() if summary else {"id": result_id}
        return {"error": "Reindexing failed"}
    finally:
        conn.close()


def _apply_frontmatter_updates(
    content: str,
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    related: list[str] | None = None,
    source_url: str = "",
    sentiment: str = "",
    status: str = "",
) -> str:
    """Update frontmatter fields in a markdown file's content string."""
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not fm_match:
        return content

    fm_text = fm_match.group(1)
    rest = content[fm_match.end():]
    lines = fm_text.split("\n")

    # Update scalar fields
    if status:
        lines = _set_fm_scalar(lines, "status", status)
    if sentiment:
        lines = _set_fm_scalar(lines, "sentiment", sentiment)
    if source_url:
        lines = _set_fm_scalar(lines, "url", f'"{source_url}"')

    # Update updated_at
    lines = _set_fm_scalar(lines, "updated_at", date.today().isoformat())

    # Append to list fields
    if tags:
        lines = _append_fm_list(lines, "tags", tags)
    if sources:
        lines = _append_fm_list(lines, "sources", [f'"[[{s}]]"' for s in sources])
    if related:
        lines = _append_fm_list(lines, "related", [f'"[[{r}]]"' for r in related])

    return "---\n" + "\n".join(lines) + "\n---\n" + rest


def _set_fm_scalar(lines: list[str], key: str, value: str) -> list[str]:
    """Set a scalar frontmatter field, adding it if missing."""
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            lines[i] = f"{key}: {value}"
            return lines
    lines.append(f"{key}: {value}")
    return lines


def _append_fm_list(lines: list[str], key: str, items: list[str]) -> list[str]:
    """Append items to a YAML list field. Handles empty list `[]` syntax."""
    # Find the key line
    key_idx = None
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            key_idx = i
            break

    if key_idx is None:
        # Add the field
        lines.append(f"{key}:")
        for item in items:
            lines.append(f"  - {item}")
        return lines

    # Check if it's an empty list: `key: []`
    if lines[key_idx].strip().endswith("[]"):
        lines[key_idx] = f"{key}:"

    # Find the end of the existing list items
    insert_at = key_idx + 1
    while insert_at < len(lines) and lines[insert_at].startswith("  - "):
        insert_at += 1

    # Collect existing items to avoid duplicates
    existing = set()
    for j in range(key_idx + 1, insert_at):
        existing.add(lines[j].strip().lstrip("- ").strip())

    # Insert new items
    for item in items:
        if item.strip() not in existing:
            lines.insert(insert_at, f"  - {item}")
            insert_at += 1

    return lines


def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
