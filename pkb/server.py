"""FastMCP server: kb_find, kb_save, kb_status."""

import os
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import config
from .dates import parse_date
from .db import get_connection, init_schema
from .embeddings import get_provider
from .indexer import Indexer, parse_markdown, file_md5, slug_from_path
from .models import NodeSummary, SearchResult, NodeDetail, StatusResult
from .search import (
    hybrid_search, fts_search, get_node, get_node_summary,
    list_nodes, get_status,
)


def _normalize_filter_date(name: str, raw: str) -> str | None:
    """Validate a user-supplied date filter param. Raises ValueError on garbage.
    Returns the normalized YYYY-MM-DD string, or None if input was empty."""
    if not raw:
        return None
    pd = parse_date(raw)
    if pd is None:
        raise ValueError(
            f"Invalid date for {name}: {raw!r}. "
            f"Expected YYYY, YYYY-MM, or YYYY-MM-DD."
        )
    return pd.start

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
Use this when the user asks about their own knowledge, notes, or things
they've previously saved — NOT for general knowledge questions.

Modes (chosen by which parameters you pass):
- Get a page: kb_find(id="agent-memory") — full content + metadata + graph
  edges. Returns None if not found.
- Search: kb_find(query="agent memory") — hybrid FTS5 + vector search.
  Returns ranked results with scores and snippets. mode="hybrid" (default)
  for best quality; "bm25" for exact keyword matching.
- Browse: anything else — no id, no query. Returns the most recent pages
  by `sort` (default: updated_at). Examples:
    kb_find(limit=10)                         → 10 most recently updated pages
    kb_find(sort="created_at", limit=20)      → 20 most recently added pages
    kb_find(origin="paper")                   → all papers
    kb_find(tag="rag")                        → pages tagged "rag"
    kb_find(created_after="2026-05-01")       → everything added since May 1
    kb_find(created_after="2026-05-06",
            sort="created_at", limit=20)      → "what did I add last week?"

Date semantics (important):
- created_at = when YOU added the page to the KB. Use created_after /
  created_before to answer "what did I add last week / this month?".
  Every result includes both `created_at` (raw ISO) and `created_relative`
  ("3 days ago"). Prefer surfacing `created_relative` in chat output.
- updated_at = last time the page's content was edited. Use updated_*
  filters only if the question is explicitly about edits.
- published_at = the source's OWN publication date (a 2018 paper added
  in 2026 has created_at=2026-…, published_at=2018-…). Use published_after /
  published_before for "papers from 2022" style queries.

Date filters use overlap semantics (matters only for partial-precision dates):
- published_at: 2022 represents the interval [2022-01-01, 2023-01-01). It
  MATCHES published_after="2022-07-01" (interval extends past July 1). It
  does NOT match published_before="2022-01-01" (interval starts on Jan 1).
- Filter inputs accept YYYY, YYYY-MM, or YYYY-MM-DD. Invalid values raise
  a tool error.
- Hybrid (vec) mode with very restrictive filters MAY return fewer than
  `limit` results because nearest neighbors fall outside the filter window.
  Use mode="bm25" if completeness matters more than semantic similarity.

Each result includes `*_relative` fields ("3 days ago", "Oct 2024", "2018")
that respect the original precision — a page with `published_at: 2018`
renders as "2018", not "Jan 2018". Prefer the relative form in chat output;
the raw ISO is there if you need exact comparisons.

Results are ranked by Reciprocal Rank Fusion score. Only ordering matters —
do not interpret raw score values as similarity percentages.

When adding new content via kb_save, search first to find existing pages
on the same topic — this avoids duplicates and helps identify related
pages to link.

DO NOT use this for general knowledge questions — use web search instead.
DO NOT guess node IDs — search first to find valid IDs."""

_SAVE_DESC = """\
Personal KB tool. Create, update, or reindex pages in the user's personal
wiki. Automatically reindexes after every write.

IMPORTANT: Before saving, always draft the proposed title, body, tags,
origin, and related links and show them to the user. Suggest relevant tags
based on the content. Get explicit approval before calling this tool.

Modes (determined by parameters):
- Create: kb_save(title="...", origin="note", body="...")
  Required: title, origin, body. Body should NOT include the # Title
  heading — the system adds it automatically.
- Update metadata: kb_save(id="...", tags=["a", "b"], related=["page-id"])
  Replaces the field with the given values. Pass [] to clear.
  Omit a parameter to leave that field unchanged.
- Update a section: kb_save(id="...", section="Summary", body="...")
  Creates the section if missing, replaces if it exists.
  Body should NOT include the ## heading.
- Replace body: kb_save(id="...", body="full new body")
- Reindex after external edit: kb_save(id="...")

Origin values: webpage, paper, conversation, note, book, transcript, meta.

Use `sources` for pages this was built FROM (creates source edges).
Use `related` for pages this is RELEVANT TO (creates related edges).
Wikilinks are pathless: use "agent-memory" not "concepts/agent-memory".

On create, returns `suggested_related` and `suggested_tags` from similar
pages. Present these to the user — if they confirm, call kb_save again
with kb_save(id="...", related=[...]) or kb_save(id="...", tags=[...]).

When saving insights from the current conversation, set origin="conversation".
If conversation_search is available, use it to find the chat URL and pass
it as source_url. Capture the actual insight in the body, not just a
reference to the discussion.

The optional `published_at` parameter records the source's own publication
date (distinct from when you're filing the page). For papers/articles/
briefings where the publication date is meaningful, pass it as YYYY,
YYYY-MM, or YYYY-MM-DD — pkb preserves the precision you specify ("2018"
stays "2018", not "Jan 2018"). Omit when unknown — never set to "".
Invalid date strings raise an error.

Does NOT fetch URLs — pass content directly in the body parameter."""

_STATUS_DESC = """\
Personal KB tool. Health check for the user's personal knowledge base index.
Returns node count, edge count, chunk count, embedding coverage percentage,
stale page count, and orphan chunk count.

Use this when the user asks about their wiki's health, or when search
results seem incomplete or unexpected. If embedding coverage is below
100%, run `pkb rebuild` to fix it."""


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
    created_after: str = "",
    created_before: str = "",
    published_after: str = "",
    published_before: str = "",
    mode: str = "hybrid",
    sort: str = "updated_at",
    limit: int = 10,
) -> dict | list[dict] | None:
    """Find and retrieve pages from the personal wiki."""
    # Validate date filter inputs up front — raise so MCP surfaces a clean
    # tool error with the descriptive message, rather than silently skipping.
    created_after_norm = _normalize_filter_date("created_after", created_after)
    created_before_norm = _normalize_filter_date("created_before", created_before)
    published_after_norm = _normalize_filter_date("published_after", published_after)
    published_before_norm = _normalize_filter_date("published_before", published_before)

    conn = _get_conn()
    try:
        # Get by ID
        if id:
            detail = get_node(conn, id)
            return detail.model_dump() if detail else None

        # Search by query
        if query:
            filters: dict = {}
            if origin:
                filters["origin"] = origin
            if sentiment:
                filters["sentiment"] = sentiment
            if created_after_norm:
                filters["created_after"] = created_after_norm
            if created_before_norm:
                filters["created_before"] = created_before_norm
            if published_after_norm:
                filters["published_after"] = published_after_norm
            if published_before_norm:
                filters["published_before"] = published_before_norm

            if mode == "bm25":
                results = fts_search(conn, query, limit=limit, filters=filters)
            else:
                provider = _get_provider(conn)
                results = hybrid_search(conn, query, limit=limit, filters=filters, embedding_provider=provider)
            return [r.model_dump() for r in results]

        # Browse — neither id nor query was given. List pages by sort + any
        # filters (origin/tag/status/date) or just return the N most recent.
        # "What's in my wiki?" / "what did I add last week?" route here.
        nodes = list_nodes(
            conn,
            origin_filter=origin, tag_filter=tag, status_filter=status,
            created_after=created_after_norm,
            created_before=created_before_norm,
            published_after=published_after_norm,
            published_before=published_before_norm,
            sort=sort, limit=limit,
        )
        return [n.model_dump() for n in nodes]
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
    published_at: str = "",
    ingested_via: str = "manual",
) -> dict:
    """Create, update, or reindex pages in the personal wiki."""
    # Validate published_at up front — raise so the LLM sees a clean error
    # rather than silently writing garbage to frontmatter.
    if published_at and parse_date(published_at) is None:
        raise ValueError(
            f"Invalid date for published_at: {published_at!r}. "
            f"Expected YYYY, YYYY-MM, or YYYY-MM-DD."
        )

    # --- Create new page ---
    if not id and title:
        return _create_page(
            title=title, origin=origin, body=body, source_url=source_url,
            tags=tags, sources=sources, related=related,
            sentiment=sentiment, ingested_via=ingested_via,
            published_at=published_at,
        )

    # --- Update or reindex existing page ---
    if id:
        return _update_page(
            node_id=id, body=body, section=section,
            tags=tags, sources=sources, related=related,
            source_url=source_url, sentiment=sentiment, status=status,
            published_at=published_at,
        )

    raise ValueError("Provide 'id' to update, or 'title' + 'origin' + 'body' to create.")


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
    published_at: str = "",
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
    if published_at:
        # Emit raw user-provided form (any precision). Indexer normalizes
        # for filter/sort but markdown is the source of truth.
        fm_lines.append(f"published_at: {published_at}")
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
    published_at: str = "",
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
        has_metadata = (tags is not None or sources is not None or related is not None
                        or source_url or sentiment or status or published_at)

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
                published_at=published_at,
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
    published_at: str = "",
) -> str:
    """Update frontmatter fields in a markdown file's content string."""
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not fm_match:
        return content

    fm_text = fm_match.group(1)
    rest = content[fm_match.end():]
    lines = fm_text.split("\n")

    # Update scalar fields. Skip emission when value is empty so we never
    # write `field: ` (omit-rather-than-empty rule).
    if status:
        lines = _set_fm_scalar(lines, "status", status)
    if sentiment:
        lines = _set_fm_scalar(lines, "sentiment", sentiment)
    if source_url:
        lines = _set_fm_scalar(lines, "url", f'"{source_url}"')
    if published_at:
        lines = _set_fm_scalar(lines, "published_at", published_at)

    # Update updated_at
    lines = _set_fm_scalar(lines, "updated_at", date.today().isoformat())

    # Replace list fields (None = don't touch, [] = clear, [...] = set)
    if tags is not None:
        lines = _replace_fm_list(lines, "tags", tags)
    if sources is not None:
        lines = _replace_fm_list(lines, "sources", [f'"[[{s}]]"' for s in sources])
    if related is not None:
        lines = _replace_fm_list(lines, "related", [f'"[[{r}]]"' for r in related])

    return "---\n" + "\n".join(lines) + "\n---\n" + rest


def _set_fm_scalar(lines: list[str], key: str, value: str) -> list[str]:
    """Set a scalar frontmatter field, adding it if missing."""
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            lines[i] = f"{key}: {value}"
            return lines
    lines.append(f"{key}: {value}")
    return lines


def _replace_fm_list(lines: list[str], key: str, items: list[str]) -> list[str]:
    """Replace a YAML list field with new items. Empty list = clear."""
    # Find the key line
    key_idx = None
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            key_idx = i
            break

    if key_idx is None:
        # Add the field
        if items:
            lines.append(f"{key}:")
            for item in items:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: []")
        return lines

    # Remove existing list items
    end_idx = key_idx + 1
    while end_idx < len(lines) and lines[end_idx].startswith("  - "):
        end_idx += 1
    del lines[key_idx + 1:end_idx]

    # Write new items
    if items:
        lines[key_idx] = f"{key}:"
        for i, item in enumerate(items):
            lines.insert(key_idx + 1 + i, f"  - {item}")
    else:
        lines[key_idx] = f"{key}: []"

    return lines


def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
