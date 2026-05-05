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
    get_neighborhood,
)

mcp = FastMCP("pkb", instructions="""\
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

Use this when the user wants to find specific pages matching a query, or
needs type/sentiment filters. Returns ranked results with titles, types,
scores, and snippets from their curated collection.

For general topic overviews ("kb: agent memory", "what do I know about X"),
prefer kb_explore instead — it returns richer context (synthesis page,
staleness, graph neighbors). Use kb_search when the user wants a ranked
list of matching pages or when kb_explore didn't surface what they need.

Results are ranked by Reciprocal Rank Fusion score. Only ordering matters —
do not interpret raw score values as similarity percentages. Use "hybrid"
mode (default) for best quality; "bm25" for exact keyword matching.

DO NOT use this for general knowledge questions — use web search instead.
DO NOT use this for browsing — use kb_list instead.
DO NOT use this if you already have a node ID — use kb_get instead."""

_EXPLORE_DESC = """\
Personal KB tool. Explore a topic in the user's personal knowledge base.
Returns the synthesis page (if one exists), staleness indicators,
unincorporated source pages, adjacent topics in the graph, and suggested
next actions.

This is the DEFAULT tool when the user asks about their KB. Use it for
trigger phrases like "kb:", "in my KB", "what do I know about", "in my
notes about", "explore:", "check my vault". It gives a structured overview
of everything the KB knows about a topic.

Prefer this over kb_search when the user wants a topic overview. Use
kb_search instead only when the user wants to find specific pages matching
a precise query or needs type/sentiment filters.

DO NOT use this for general knowledge questions — use web search instead.
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

The `origin` parameter specifies provenance — what kind of content this is:
webpage, paper, conversation, note, book, transcript, meta.

Use the `related` parameter to declare connections to existing pages (e.g.,
related=["agent-memory"]). This creates graph edges that surface during
kb_explore. Use `sources` for pages this was built FROM; use `related` for
pages this is RELEVANT TO. Wikilinks are pathless: use "agent-memory" not
"concepts/agent-memory".

Does NOT trigger compilation — the caller decides when to compile.
Does NOT fetch URLs — pass the content directly in the body parameter.
Returns the indexed node summary on success, plus `suggested_related` —
a list of existing pages that are semantically similar. The user can
confirm which suggestions to link."""

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
coverage is below 100%, run `python -m pkb rebuild` to fix it."""


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


@mcp.tool(description=_SEARCH_DESC)
def kb_search(
    query: str,
    limit: int = 10,
    origin: str | None = None,
    sentiment: str | None = None,
    mode: str = "hybrid",
) -> list[dict]:
    """Hybrid FTS5 + vector search with Reciprocal Rank Fusion."""
    conn = _get_conn()
    filters = {}
    if origin:
        filters["origin"] = origin
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
    origin: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    sort: str = "updated_at",
    limit: int = 50,
) -> list[dict]:
    """Filtered/sorted listing of nodes."""
    conn = _get_conn()
    try:
        nodes = list_nodes(conn, origin_filter=origin, tag_filter=tag,
                          status_filter=status, sort=sort, limit=limit)
        return [n.model_dump() for n in nodes]
    finally:
        conn.close()


@mcp.tool(description=_ADD_DESC)
def kb_add(
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
    """Add a new page to the vault."""
    tags = tags or []
    sources = sources or []
    related = related or []

    # Derive file path — flat structure, no subdirectories
    slug = _slugify(title)
    file_path = config.WIKI_DIR / f"{slug}.md"

    # Check for conflicts
    if file_path.exists():
        return {"error": f"File already exists: {file_path.relative_to(config.VAULT_ROOT)}. Use kb_get + manual edit."}

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

    full_content = "\n".join(fm_lines) + f"\n\n# {title}\n\n## Notes\n\n" + body

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

            # Auto-suggest related pages (exclude self, meta, already-declared)
            meta_pages = {"index", "log", "hot"}
            declared_set = set(related) | set(sources)
            try:
                suggestions = hybrid_search(conn, body[:2000], limit=5, embedding_provider=provider)
                result["suggested_related"] = [
                    {"id": s.node_id, "title": s.title}
                    for s in suggestions
                    if s.node_id != node_id
                    and s.node_id not in meta_pages
                    and s.node_id not in declared_set
                ][:3]
            except Exception:
                result["suggested_related"] = []

            return result
        return {"error": "Indexing failed"}
    finally:
        conn.close()


@mcp.tool(description=_SYNTHESIZE_DESC)
def kb_synthesize(node_id: str, source_ids: list[str] | None = None) -> str:
    """Assemble a synthesis prompt for rewriting a page."""
    source_ids = source_ids or []
    conn = _get_conn()
    try:
        provider = _get_provider(conn)
        existing = get_node(conn, node_id)

        source_pages = []
        for sid in source_ids:
            page = get_node(conn, sid)
            if page:
                source_pages.append(page)

        existing_title = existing.title if existing else node_id

        # Extract only the ## Synthesis section for section-protected compilation
        from .markdown import extract_section
        if existing:
            existing_synthesis = extract_section(existing.body, "Synthesis")
        else:
            existing_synthesis = ""

        sources_text = ""
        for sp in source_pages:
            sources_text += f"\n\n### [[{sp.id}]] — {sp.title}\n"
            sources_text += f"Origin: {sp.origin} | Updated: {sp.updated_at}\n"
            sources_text += sp.body[:3000]

        # Scoped wikilink candidates: semantic search + graph neighbors
        candidate_ids = set()
        try:
            search_hits = hybrid_search(conn, existing_title, limit=30, embedding_provider=provider)
            candidate_ids |= {h.node_id for h in search_hits}
        except Exception:
            pass
        neighbors = get_neighborhood(conn, node_id, radius=1)
        candidate_ids |= {n.id for n in neighbors}
        candidate_ids.discard(node_id)

        if candidate_ids:
            placeholders = ",".join("?" * len(candidate_ids))
            available = conn.execute(
                f"SELECT id, title FROM nodes WHERE id IN ({placeholders}) AND origin != 'meta'",
                list(candidate_ids),
            ).fetchall()
            page_list = "\n".join(f"- [[{r['id']}]] ({r['title']})" for r in available)
        else:
            page_list = "(no linkable pages found)"

        return f"""## Synthesis task

Write or update the ## Synthesis section for [[{node_id}]] ({existing_title}).

### Current synthesis section
{existing_synthesis if existing_synthesis else "(no existing synthesis — create from scratch)"}

### Sources to incorporate
{sources_text if sources_text else "(no new sources specified)"}

### Rules
- Return ONLY the content for the ## Synthesis section. Do NOT include the ## Synthesis heading itself.
- Write a coherent synthesis that incorporates all sources. Do not just list them.
- Update the `updated_at:` frontmatter field to today ({date.today().isoformat()}).
- Add each new source to the `sources: []` list in frontmatter.
- If any new source contradicts existing content, add a > [!contradiction] callout.
- Preserve the frontmatter schema (flat YAML, all required fields).
- When referring to concepts, entities, or topics that exist in the wiki, use [[slug]] wikilink notation inline in the prose. Only link to pages in this list:
{page_list}
- After writing the updated file to disk, you MUST immediately call kb_reindex(node_id="{node_id}") to update the search index. Do not proceed with other operations until reindexing completes.
- Use the replace_or_insert_section helper or manually splice the synthesis content into the page, preserving all other sections (## Notes, etc.) untouched.
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
