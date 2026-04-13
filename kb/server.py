"""FastMCP server: kb_add, kb_search, kb_explore, kb_synthesize, kb_get, kb_list, kb_reindex, kb_status."""

import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import config
from .db import get_connection, init_schema
from .embeddings import get_provider
from .indexer import Indexer, parse_markdown, file_md5, slug_from_path
from .models import NodeSummary, SearchResult, NodeDetail, ExploreResult, StatusResult
from .search import (
    hybrid_search, fts_search, get_node, get_node_summary,
    list_nodes, get_status, explore, get_source_chain, get_derived_pages,
)

mcp = FastMCP("kb", instructions="""\
Personal knowledge base tools. These access the user's PERSONAL compiled \
wiki of notes, ingested articles, papers, and synthesis pages — NOT the \
public internet. Topics include AI tooling, agent memory, MCP ecosystem, \
LLM context scaling, AI coding agents, and computational social science, \
but the collection grows over time.

Only use these tools when the user asks about their personal notes, KB, \
wiki, or vault. Trigger phrases: "in my KB", "in my notes", "check my \
vault", "what do I know about", "explore:", "query:", "kb:". For general \
knowledge questions, prefer web search or your own training data.""")

_KB_TOKEN = os.getenv("KB_MCP_TOKEN")

# --- Tool description constants ---

_SEARCH_DESC = """\
Personal KB tool. Search the user's personal knowledge base using hybrid
retrieval (FTS5 + vector + RRF).

Use this when the user asks to find something in their notes, wiki, or
vault. Returns ranked results with titles, types, scores, and snippets
from their curated collection.

Results are ranked by Reciprocal Rank Fusion score. Only ordering matters —
do not interpret raw score values as similarity percentages.

Use "hybrid" mode (default) for best quality. Use "bm25" for exact keyword
matching when you know the precise terms used in the KB.

DO NOT use this for general knowledge questions — use web search instead.
DO NOT use this for browsing — use kb_list instead.
DO NOT use this if you already have a node ID — use kb_get instead.
For structured exploration with staleness detection, use kb_explore."""

_EXPLORE_DESC = """\
Personal KB tool. Explore a topic in the user's personal knowledge base.
Returns the synthesis page (if one exists), staleness indicators,
unincorporated source pages, adjacent topics in the graph, and suggested
next actions.

Use this when the user asks what they know about a topic, what they've
read, or wants to explore their notes on a subject. It shows what the KB
already knows, what's stale, and what's missing.

DO NOT use this for general knowledge questions — use web search instead.
DO NOT use this for raw keyword search — use kb_search instead.
DO NOT use this to retrieve a specific page — use kb_get instead."""

_GET_DESC = """\
Personal KB tool. Retrieve full page content, metadata, and edges (sources,
sourced_by, related) from the user's personal wiki.

Use this after kb_search or kb_explore returns a node ID the user wants to
read in full. Returns the complete markdown body plus frontmatter fields and
graph edges.

DO NOT guess node IDs — search or explore first to find valid IDs."""

_LIST_DESC = """\
Personal KB tool. Browse and filter pages in the user's personal wiki by
type, tag, or status. Returns summaries sorted by the chosen field.

Use this when the user wants to see what's in their KB — inventorying
pages, filtering by topic area, or browsing recent additions.

DO NOT use this for general knowledge questions — use web search instead.
DO NOT use this for semantic search — use kb_search instead.
DO NOT use this if you already have a node ID — use kb_get instead."""

_ADD_DESC = """\
Personal KB tool. Add a new page to the user's personal wiki. Writes a
markdown file with frontmatter and indexes it in SQLite immediately. The
page is searchable right away.

Does NOT trigger compilation — the caller decides when to compile.
Does NOT fetch URLs — pass the content directly in the body parameter.
Returns the indexed node summary on success."""

_SYNTHESIZE_DESC = """\
Personal KB tool. Assemble a synthesis/compilation prompt for rewriting a
page in the user's personal wiki. Returns a structured string containing
the current page content, source pages to incorporate, and rewrite rules.

This tool does NOT call an LLM — it returns context for the calling LLM to
use when rewriting the page. After using the returned prompt to rewrite the
file, you MUST call kb_reindex on the rewritten file.

DO NOT call this without reading the result — it contains critical rewrite
rules including the reindex requirement."""

_REINDEX_DESC = """\
Personal KB tool. Re-index a single file after writing or editing it in the
user's wiki. Updates FTS5, embeddings, and graph edges in the SQLite database.

You MUST call this after every file write or edit during compilation. Without
this, search results will be stale and graph edges will be wrong.

Accepts either file_path (relative to vault root or absolute) or node_id.
Do NOT run multiple kb_reindex calls in parallel — execute them sequentially
to avoid SQLite database locking errors."""

_STATUS_DESC = """\
Personal KB tool. Health check for the user's personal knowledge base index.
Returns node count, edge count, chunk count, embedding coverage percentage,
stale page count, and orphan chunk count.

Use this to verify the index is healthy before searching. If embedding
coverage is below 100%, run `python -m kb rebuild` to fix it."""


def _get_conn():
    """Get a DB connection, initializing schema if needed."""
    conn = get_connection()
    init_schema(conn)
    return conn


def _get_provider(conn):
    """Get the embedding provider with caching."""
    provider_name = os.getenv("KB_EMBEDDING_PROVIDER", config.EMBEDDING_PROVIDER)
    return get_provider(provider_name, conn=conn)


@mcp.tool(description=_SEARCH_DESC)
def kb_search(
    query: str,
    limit: int = 10,
    type: str | None = None,
    sentiment: str | None = None,
    mode: str = "hybrid",
) -> list[dict]:
    """Hybrid FTS5 + vector search with Reciprocal Rank Fusion."""
    conn = _get_conn()
    filters = {}
    if type:
        filters["type"] = type
    if sentiment:
        filters["sentiment"] = sentiment

    try:
        if mode == "bm25":
            results = fts_search(conn, query, limit=limit, filters=filters)
        else:
            provider = _get_provider(conn)
            results = hybrid_search(conn, query, limit=limit, filters=filters, embedding_provider=provider)
        return [r.model_dump() for r in results]
    finally:
        conn.close()


@mcp.tool(description=_EXPLORE_DESC)
def kb_explore(topic: str) -> dict:
    """Interactive exploration of a topic."""
    conn = _get_conn()
    try:
        provider = _get_provider(conn)
        result = explore(conn, topic, embedding_provider=provider)
        return result.model_dump()
    finally:
        conn.close()


@mcp.tool(description=_GET_DESC)
def kb_get(node_id: str) -> dict | None:
    """Get full page content + metadata + edges."""
    conn = _get_conn()
    try:
        detail = get_node(conn, node_id)
        return detail.model_dump() if detail else None
    finally:
        conn.close()


@mcp.tool(description=_LIST_DESC)
def kb_list(
    type: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    sort: str = "updated",
    limit: int = 50,
) -> list[dict]:
    """Filtered/sorted listing of nodes."""
    conn = _get_conn()
    try:
        nodes = list_nodes(conn, type_filter=type, tag_filter=tag,
                          status_filter=status, sort=sort, limit=limit)
        return [n.model_dump() for n in nodes]
    finally:
        conn.close()


@mcp.tool(description=_ADD_DESC)
def kb_add(
    title: str,
    type: str,
    body: str,
    source_url: str = "",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    sentiment: str = "",
    ingested_via: str = "manual",
) -> dict:
    """Add a new page to the vault."""
    tags = tags or []
    sources = sources or []

    # Derive file path
    slug = _slugify(title)
    type_dirs = {
        "source": "sources", "entity": "entities", "concept": "concepts",
        "question": "questions", "comparison": "concepts",
        "overview": "concepts", "meta": "meta", "domain": "concepts",
    }
    subdir = type_dirs.get(type, "concepts")
    file_path = config.WIKI_DIR / subdir / f"{slug}.md"

    # Check for conflicts
    if file_path.exists():
        return {"error": f"File already exists: {file_path.relative_to(config.VAULT_ROOT)}. Use kb_get + manual edit."}

    # Generate frontmatter
    today = date.today().isoformat()
    fm_lines = [
        "---",
        f"type: {type}",
        f'title: "{title}"',
        f"created: {today}",
        f"updated: {today}",
        "status: seed",
    ]
    if tags:
        fm_lines.append("tags:")
        for t in tags:
            fm_lines.append(f"  - {t}")
    if source_url:
        fm_lines.append(f'url: "{source_url}"')
    if sentiment:
        fm_lines.append(f"sentiment: {sentiment}")
    if ingested_via:
        fm_lines.append(f"ingested_via: {ingested_via}")
    if sources:
        fm_lines.append("sources:")
        for s in sources:
            fm_lines.append(f'  - "[[{s}]]"')
    fm_lines.append("related: []")
    fm_lines.append("---")

    full_content = "\n".join(fm_lines) + "\n\n" + body

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
            return summary.model_dump() if summary else {"id": node_id, "file_path": str(file_path)}
        return {"error": "Indexing failed"}
    finally:
        conn.close()


@mcp.tool(description=_SYNTHESIZE_DESC)
def kb_synthesize(node_id: str, source_ids: list[str] | None = None) -> str:
    """Assemble a synthesis prompt for rewriting a page."""
    source_ids = source_ids or []
    conn = _get_conn()
    try:
        existing = get_node(conn, node_id)

        source_pages = []
        for sid in source_ids:
            page = get_node(conn, sid)
            if page:
                source_pages.append(page)

        existing_body = existing.body if existing else "(new page -- create from scratch)"
        existing_title = existing.title if existing else node_id

        sources_text = ""
        for sp in source_pages:
            sources_text += f"\n\n### [[{sp.id}]] — {sp.title}\n"
            sources_text += f"Type: {sp.type} | Updated: {sp.updated}\n"
            sources_text += sp.body[:3000]

        return f"""## Synthesis task

Rewrite [[{node_id}]] to incorporate the following new sources.

### Current page content ({existing_title})
{existing_body}

### Sources to incorporate
{sources_text if sources_text else "(no new sources specified)"}

### Rules
- Rewrite the existing page, don't append. The page should read as a coherent whole.
- Update the `updated:` frontmatter field to today ({date.today().isoformat()}).
- Add each new source to the `sources: []` list in frontmatter.
- If any new source contradicts existing content, add a > [!contradiction] callout.
- Preserve the frontmatter schema (flat YAML, all required fields).
- After writing the updated file to disk, you MUST immediately call kb_reindex(node_id="{node_id}") to update the search index. Do not proceed with other operations until reindexing completes.
"""
    finally:
        conn.close()


@mcp.tool(description=_REINDEX_DESC)
def kb_reindex(file_path: str = "", node_id: str = "") -> dict:
    """Re-index a single file after writing or editing it."""
    conn = _get_conn()
    try:
        if node_id and not file_path:
            row = conn.execute("SELECT file_path FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if row:
                file_path = row["file_path"]
            else:
                return {"error": f"Node not found: {node_id}"}

        if not file_path:
            return {"error": "Provide file_path or node_id"}

        # Resolve to absolute path
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = config.VAULT_ROOT / fp

        if not fp.exists():
            return {"error": f"File not found: {fp}"}

        # Flush detection: wait for write to complete
        for _ in range(5):
            mtime1, size1 = fp.stat().st_mtime, fp.stat().st_size
            time.sleep(0.05)
            mtime2, size2 = fp.stat().st_mtime, fp.stat().st_size
            if mtime1 == mtime2 and size1 == size2 and size1 > 0:
                break

        provider = _get_provider(conn)
        indexer = Indexer(conn, embedding_provider=provider)
        result_id = indexer.index_single(fp)

        if result_id:
            summary = get_node_summary(conn, result_id)
            return summary.model_dump() if summary else {"id": result_id}
        return {"error": "Indexing failed"}
    finally:
        conn.close()


@mcp.tool(description=_STATUS_DESC)
def kb_status() -> dict:
    """Index health check."""
    conn = _get_conn()
    try:
        status = get_status(conn)
        return status.model_dump()
    finally:
        conn.close()


def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
