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

mcp = FastMCP("kb", instructions="Knowledge base search and exploration tools.")


def _get_conn():
    """Get a DB connection, initializing schema if needed."""
    conn = get_connection()
    init_schema(conn)
    return conn


def _get_provider(conn):
    """Get the embedding provider with caching."""
    provider_name = os.getenv("KB_EMBEDDING_PROVIDER", config.EMBEDDING_PROVIDER)
    return get_provider(provider_name, conn=conn)


@mcp.tool()
def kb_search(
    query: str,
    limit: int = 10,
    type: str | None = None,
    sentiment: str | None = None,
    mode: str = "hybrid",
) -> list[dict]:
    """Hybrid FTS5 + vector search with Reciprocal Rank Fusion.

    Args:
        query: Natural-language search query.
        limit: Max results (default 10).
        type: Filter by node type (source, entity, concept, etc.).
        sentiment: Filter by sentiment (critical, skeptical, neutral, etc.).
        mode: "hybrid" (default) or "bm25" (keyword only).
    """
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


@mcp.tool()
def kb_explore(topic: str) -> dict:
    """Interactive exploration: returns synthesis page, staleness, unincorporated sources,
    adjacent topics, and suggested actions.

    Args:
        topic: Topic to explore (natural language or node ID).
    """
    conn = _get_conn()
    try:
        provider = _get_provider(conn)
        result = explore(conn, topic, embedding_provider=provider)
        return result.model_dump()
    finally:
        conn.close()


@mcp.tool()
def kb_get(node_id: str) -> dict | None:
    """Get full page content + metadata + edges.

    Args:
        node_id: Node ID (e.g., "concepts/ai-coding-agents").
    """
    conn = _get_conn()
    try:
        detail = get_node(conn, node_id)
        return detail.model_dump() if detail else None
    finally:
        conn.close()


@mcp.tool()
def kb_list(
    type: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    sort: str = "updated",
    limit: int = 50,
) -> list[dict]:
    """Filtered/sorted listing of nodes. For browsing, not searching.

    Args:
        type: Filter by node type.
        tag: Filter by tag.
        status: Filter by status.
        sort: Sort field: "updated", "created", or "title".
        limit: Max results.
    """
    conn = _get_conn()
    try:
        nodes = list_nodes(conn, type_filter=type, tag_filter=tag,
                          status_filter=status, sort=sort, limit=limit)
        return [n.model_dump() for n in nodes]
    finally:
        conn.close()


@mcp.tool()
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
    """Add a new page to the vault. Writes markdown + indexes in SQLite.

    Does NOT trigger compilation. The caller decides when to compile.

    Args:
        title: Page title.
        type: Page type (source, entity, concept, etc.).
        body: Markdown body content.
        source_url: Optional URL of the original source.
        tags: Optional list of tags.
        sources: Optional list of source node IDs.
        sentiment: Optional sentiment (critical, skeptical, neutral, etc.).
        ingested_via: Provenance (manual, notion_briefing, web_fetch, etc.).
    """
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


@mcp.tool()
def kb_synthesize(node_id: str, source_ids: list[str] | None = None) -> str:
    """Assemble a synthesis prompt. Returns structured context for the calling LLM
    to rewrite the page. The MCP tool does NOT call an LLM.

    Args:
        node_id: The synthesis page to rewrite (or create).
        source_ids: List of source node IDs to incorporate.
    """
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
"""
    finally:
        conn.close()


@mcp.tool()
def kb_reindex(file_path: str = "", node_id: str = "") -> dict:
    """Re-index a single file after the LLM writes/edits it.

    Must be called after every file write during compilation.

    Args:
        file_path: Path to the file (relative to vault root or absolute).
        node_id: Alternative: node ID to re-index.
    """
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


@mcp.tool()
def kb_status() -> dict:
    """Index health: page count, stale count, orphan count, embedding coverage."""
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
