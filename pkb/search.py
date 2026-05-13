"""Hybrid search (FTS5 + sqlite-vec + RRF), graph traversal, staleness, explore."""

import os
import struct
from datetime import datetime, date

from . import config
from .models import SearchResult, NodeSummary, NodeDetail, ExploreResult, StatusResult
from .embeddings import EmbeddingProvider, get_provider


# ── Column selection helpers ───────────────────────────────────────────
# Single source of truth for "which nodes columns do we hydrate models with"
# so future column additions are a one-line change instead of editing
# eleven SELECT sites.

_NODE_VIEW_COLS = (
    "n.id, n.title, n.origin, "
    "n.created_at, n.updated_at, "
    "n.published_at, n.published_at_start, n.published_at_precision, "
    "n.file_path, n.body"
)


def _row_to_summary(r, snippet_len: int = 200) -> NodeSummary:
    """Hydrate a nodes row into a NodeSummary. Row must include _NODE_VIEW_COLS."""
    return NodeSummary(
        id=r["id"], title=r["title"], origin=r["origin"],
        created_at=_safe(r, "created_at"),
        updated_at=r["updated_at"] or "",
        published_at=_safe(r, "published_at"),
        published_at_start=_safe(r, "published_at_start"),
        published_at_precision=_safe(r, "published_at_precision"),
        file_path=_safe(r, "file_path") or "",
        snippet=(r["body"][:snippet_len] if "body" in r.keys() and r["body"] else ""),
    )


def _row_to_search_result(r, score: float, vec_distance: float | None = None,
                          snippet_len: int = 300) -> SearchResult:
    """Hydrate a nodes row into a SearchResult."""
    return SearchResult(
        node_id=r["id"], title=r["title"], origin=r["origin"],
        created_at=_safe(r, "created_at"),
        updated_at=r["updated_at"] or "",
        published_at=_safe(r, "published_at"),
        published_at_start=_safe(r, "published_at_start"),
        published_at_precision=_safe(r, "published_at_precision"),
        score=score,
        vec_distance=vec_distance,
        snippet=(r["body"][:snippet_len] if "body" in r.keys() and r["body"] else ""),
    )


def _safe(row, key: str):
    """Return row[key] if the column is present in the row, else None.
    Lets the same helper work with SELECTs that don't include every view column."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


# ── Date filter helpers ───────────────────────────────────────────────

def _build_date_predicates(filters: dict) -> tuple[str, list]:
    """Translate normalized date filter strings into SQL WHERE clauses.

    Filters are pre-validated by the caller (see server.kb_find) — values
    here are full YYYY-MM-DD strings or absent.

    Semantics (overlap, see CLAUDE.md / _FIND_DESC):
      - created_after  → n.created_at >= X
      - created_before → n.created_at <  X
      - published_after  → n.published_at_end   > X  (interval extends past X)
      - published_before → n.published_at_start < X  (interval begins before X)
    """
    clauses: list[str] = []
    params: list = []
    if v := filters.get("created_after"):
        clauses.append("n.created_at >= ?")
        params.append(v)
    if v := filters.get("created_before"):
        clauses.append("n.created_at < ?")
        params.append(v)
    if v := filters.get("published_after"):
        clauses.append("n.published_at_end > ?")
        params.append(v)
    if v := filters.get("published_before"):
        clauses.append("n.published_at_start < ?")
        params.append(v)
    return (" AND ".join(clauses), params)


def _row_passes_date_filters(row, filters: dict) -> bool:
    """Python-side equivalent of _build_date_predicates for the vec post-filter path.
    Row must carry created_at and the two published_at_* interval columns when
    those filters are set."""
    if v := filters.get("created_after"):
        if not row["created_at"] or row["created_at"] < v:
            return False
    if v := filters.get("created_before"):
        if not row["created_at"] or row["created_at"] >= v:
            return False
    if v := filters.get("published_after"):
        if not row["published_at_end"] or row["published_at_end"] <= v:
            return False
    if v := filters.get("published_before"):
        if not row["published_at_start"] or row["published_at_start"] >= v:
            return False
    return True


# ── Hybrid search ─────────────────────────────────────────────────────

def hybrid_search(
    conn,
    query: str,
    limit: int = 10,
    filters: dict | None = None,
    weights: tuple[float, float] = (0.5, 0.5),
    embedding_provider: EmbeddingProvider | None = None,
) -> list[SearchResult]:
    """FTS5 + sqlite-vec hybrid search with Reciprocal Rank Fusion.

    Args:
        conn: SQLite connection with extensions loaded.
        query: Natural-language query string.
        limit: Max results to return.
        filters: Optional dict of field=value filters (type, sentiment, etc.)
        weights: (fts_weight, vec_weight) for RRF scoring.
        embedding_provider: For computing query embedding. If None, FTS5-only.
    """
    filters = filters or {}
    fts_weight, vec_weight = weights
    candidate_limit = max(limit * 5, 50)  # generous candidate pool

    # Build filter clauses
    origin_filter = filters.get("origin")
    sentiment_filter = filters.get("sentiment")

    # ── FTS5 results ──
    fts_results = _fts_search(conn, query, origin_filter, sentiment_filter, candidate_limit, filters)

    # ── Vector results ──
    vec_results = []
    if embedding_provider and vec_weight > 0:
        vec_results = _vec_search(conn, query, embedding_provider, origin_filter, sentiment_filter, candidate_limit, filters)

    # ── RRF fusion ──
    scores: dict[str, float] = {}
    vec_distances: dict[str, float] = {}

    k = 60.0  # RRF constant
    for rank, node_id in enumerate(fts_results, 1):
        scores[node_id] = scores.get(node_id, 0) + fts_weight * (1.0 / (k + rank))

    for rank, (node_id, distance) in enumerate(vec_results, 1):
        scores[node_id] = scores.get(node_id, 0) + vec_weight * (1.0 / (k + rank))
        # Keep best (lowest) distance per node
        if node_id not in vec_distances or distance < vec_distances[node_id]:
            vec_distances[node_id] = distance

    # Demote structural/navigation pages (index, log) to avoid polluting results
    for meta_id in config.META_NODE_IDS:
        if meta_id in scores:
            scores[meta_id] *= 0.5

    # Sort by RRF score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    # Fetch metadata for results
    results = []
    for node_id, score in ranked:
        row = conn.execute(
            f"SELECT {_NODE_VIEW_COLS} FROM nodes n WHERE n.id = ?",
            (node_id,),
        ).fetchone()
        if row:
            results.append(_row_to_search_result(row, score=score,
                                                  vec_distance=vec_distances.get(node_id)))

    return results


def fts_search(
    conn,
    query: str,
    limit: int = 10,
    filters: dict | None = None,
) -> list[SearchResult]:
    """FTS5-only search (BM25). Useful for keyword matching and negative tests."""
    filters = filters or {}
    origin_filter = filters.get("origin")
    sentiment_filter = filters.get("sentiment")

    # Request more candidates to allow for meta demotion
    fts_ids = _fts_search(conn, query, origin_filter, sentiment_filter,
                          limit + len(config.META_NODE_IDS), filters)

    # Demote structural pages by moving them to the end
    content_ids = [nid for nid in fts_ids if nid not in config.META_NODE_IDS]
    meta_ids = [nid for nid in fts_ids if nid in config.META_NODE_IDS]
    fts_ids = (content_ids + meta_ids)[:limit]

    results = []
    for rank, node_id in enumerate(fts_ids, 1):
        row = conn.execute(
            f"SELECT {_NODE_VIEW_COLS} FROM nodes n WHERE n.id = ?",
            (node_id,),
        ).fetchone()
        if row:
            results.append(_row_to_search_result(row, score=1.0 / (60.0 + rank)))

    return results


def _fts_search(
    conn,
    query: str,
    origin_filter: str | None,
    sentiment_filter: str | None,
    limit: int,
    filters: dict | None = None,
) -> list[str]:
    """Run FTS5 search, return ordered node IDs."""
    # Escape FTS5 special characters and build a safe query
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []

    sql = """
        SELECT f.node_id
        FROM nodes_fts f
        JOIN nodes n ON n.id = f.node_id
        WHERE nodes_fts MATCH ?
    """
    params: list = [fts_query]

    if origin_filter:
        sql += " AND n.origin = ?"
        params.append(origin_filter)
    if sentiment_filter:
        sql += " AND n.sentiment = ?"
        params.append(sentiment_filter)

    # Date filters — pushed into SQL so filter-then-limit semantics hold
    date_clauses, date_params = _build_date_predicates(filters or {})
    if date_clauses:
        sql += " AND " + date_clauses
        params.extend(date_params)

    sql += " ORDER BY bm25(nodes_fts, 10.0, 5.0, 2.0) LIMIT ?"
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
        return [row["node_id"] for row in rows]
    except Exception:
        # FTS5 query syntax error — fall back to simple prefix search
        return []


def _sanitize_fts_query(query: str) -> str:
    """Convert a natural language query into a safe FTS5 query.

    Strategy: extract alphanumeric words, quote each (prevents FTS5 syntax
    errors), join with OR for recall. Short stopwords (<=2 chars) are dropped.

    FTS5 BM25 ranking naturally pushes multi-word matches above single-word
    matches, so OR is fine for recall — BM25 handles precision via scoring.
    """
    import re
    words = re.findall(r'\w+', query)
    if not words:
        return ""
    # Drop very short words (stopword-like: "on", "in", "at", "is", etc.)
    # and common English stopwords that cause false positives
    stopwords = {"the", "and", "for", "that", "this", "with", "from", "are",
                 "was", "were", "been", "being", "have", "has", "had", "its",
                 "not", "but", "what", "when", "where", "how", "who", "which",
                 "about", "does", "did"}
    significant = [w for w in words if len(w) >= 3 and w.lower() not in stopwords]
    if not significant:
        significant = [w for w in words if len(w) >= 2]
    if not significant:
        return ""
    # Quote each word to prevent FTS5 syntax errors
    quoted = [f'"{w}"' for w in significant]
    return " OR ".join(quoted)


def _vec_search(
    conn,
    query: str,
    provider: EmbeddingProvider,
    origin_filter: str | None,
    sentiment_filter: str | None,
    limit: int,
    filters: dict | None = None,
) -> list[tuple[str, float]]:
    """Run vector search, return list of (node_id, distance).

    Date filters degrade vec recall — top-K nearest may not all pass the date
    predicate. Mitigation: over-fetch (with floor 100, no hard ceiling) and
    post-filter in Python. The over-fetch factor is large enough to cover
    most reasonable filter restrictivenesses on a personal-scale corpus.

    Forcing the over-fetch path even when sqlite-vec prefilter support is
    added in the future: set PKB_VEC_FORCE_OVERFETCH=1 (used by tests to
    keep the fallback path live).

    sqlite-vec's vec0 requires `k=?` in the WHERE clause for knn queries
    and doesn't support arbitrary JOINs in the knn query itself. So we:
    1. Run the knn query on chunks_vec alone (with generous k)
    2. Join with chunks + nodes in Python for filtering
    """
    filters = filters or {}
    has_date_filter = any(filters.get(k) for k in
                          ("created_after", "created_before",
                           "published_after", "published_before"))

    try:
        query_embedding = provider.embed([query], input_type="query")[0]
    except Exception:
        return []

    emb_bytes = struct.pack(f"{len(query_embedding)}f", *query_embedding)

    # Over-fetch: scale with limit, generous floor, no hard ceiling.
    # SQLite handles a few hundred rows trivially on local hardware.
    k = max(limit * 5, 100) if (has_date_filter or origin_filter or sentiment_filter) else max(limit * 5, 50)

    try:
        rows = conn.execute(
            "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ?",
            (emb_bytes, k),
        ).fetchall()
    except Exception:
        return []

    if not rows:
        return []

    # Step 2: join with chunks + nodes for metadata and filtering
    seen: dict[str, float] = {}
    for row in rows:
        chunk_id = row["rowid"]
        distance = row["distance"]

        # Look up the chunk's node
        chunk_row = conn.execute(
            "SELECT node_id FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if not chunk_row:
            continue

        node_id = chunk_row["node_id"]

        # Apply filters — fetch the node row once if any filter is active
        if origin_filter or sentiment_filter or has_date_filter:
            node_row = conn.execute(
                "SELECT origin, sentiment, created_at, "
                "published_at_start, published_at_end FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if not node_row:
                continue
            if origin_filter and node_row["origin"] != origin_filter:
                continue
            if sentiment_filter and node_row["sentiment"] != sentiment_filter:
                continue
            if has_date_filter and not _row_passes_date_filters(node_row, filters):
                continue

        # Keep best (lowest) distance per node
        if node_id not in seen or distance < seen[node_id]:
            seen[node_id] = distance

    # Return ordered by distance
    return sorted(seen.items(), key=lambda x: x[1])[:limit]


# ── Node retrieval ────────────────────────────────────────────────────

def get_node(conn, node_id: str) -> NodeDetail | None:
    """Get full node details including edges."""
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not row:
        return None

    tags = [r["tag"] for r in conn.execute("SELECT tag FROM tags WHERE node_id = ?", (node_id,))]
    aliases = [r["alias"] for r in conn.execute("SELECT alias FROM aliases WHERE node_id = ?", (node_id,))]

    # Source edges (this page's declared sources)
    sources = _get_edge_targets(conn, node_id, "source")
    # Sourced-by edges (pages that cite this one as a source)
    sourced_by = _get_edge_sources(conn, node_id, "source")
    # Related edges
    related = _get_edge_targets(conn, node_id, "related")
    # Wikilinks out
    wikilinks = [r["to_id"] for r in conn.execute(
        "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'link'", (node_id,)
    )]

    return NodeDetail(
        id=row["id"],
        file_path=row["file_path"],
        title=row["title"],
        origin=row["origin"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        published_at=row["published_at"],
        published_at_start=row["published_at_start"],
        published_at_precision=row["published_at_precision"],
        body=row["body"],
        word_count=row["word_count"] or 0,
        tags=tags,
        aliases=aliases,
        sentiment=row["sentiment"],
        url=row["url"],
        author=row["author"],
        sources=sources,
        sourced_by=sourced_by,
        related=related,
        wikilinks_out=wikilinks,
    )


def get_node_summary(conn, node_id: str) -> NodeSummary | None:
    """Get a lightweight node summary."""
    row = conn.execute(
        f"SELECT {_NODE_VIEW_COLS} FROM nodes n WHERE n.id = ?",
        (node_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_summary(row, snippet_len=300)


def _get_edge_targets(conn, from_id: str, edge_type: str) -> list[NodeSummary]:
    """Get nodes that from_id links TO via edge_type."""
    rows = conn.execute(f"""
        SELECT {_NODE_VIEW_COLS}
        FROM edges e
        JOIN nodes n ON n.id = e.to_id
        WHERE e.from_id = ? AND e.edge_type = ?
    """, (from_id, edge_type)).fetchall()
    return [_row_to_summary(r) for r in rows]


def _get_edge_sources(conn, to_id: str, edge_type: str) -> list[NodeSummary]:
    """Get nodes that link TO to_id via edge_type (reverse direction)."""
    rows = conn.execute(f"""
        SELECT {_NODE_VIEW_COLS}
        FROM edges e
        JOIN nodes n ON n.id = e.from_id
        WHERE e.to_id = ? AND e.edge_type = ?
    """, (to_id, edge_type)).fetchall()
    return [_row_to_summary(r) for r in rows]


# ── Graph traversal ───────────────────────────────────────────────────

def get_source_chain(conn, node_id: str, max_depth: int = 10) -> list[dict]:
    """Walk up 'source' edges: what was this page built from?"""
    rows = conn.execute("""
        WITH RECURSIVE chain AS (
            SELECT id, title, origin, 0 AS depth, ',' || id || ',' AS path
            FROM nodes WHERE id = :start_id

            UNION ALL

            SELECT n.id, n.title, n.origin, c.depth + 1, c.path || n.id || ','
            FROM nodes n
            JOIN edges e ON e.to_id = n.id
            JOIN chain c ON e.from_id = c.id
            WHERE e.edge_type = 'source'
              AND c.depth < :max_depth
              AND instr(c.path, ',' || n.id || ',') = 0
        )
        SELECT DISTINCT id, title, origin, depth FROM chain ORDER BY depth
    """, {"start_id": node_id, "max_depth": max_depth}).fetchall()

    return [{"id": r["id"], "title": r["title"], "origin": r["origin"], "depth": r["depth"]} for r in rows]


def get_derived_pages(conn, node_id: str, max_depth: int = 10) -> list[dict]:
    """Walk down: what pages cite this one as a source?"""
    rows = conn.execute("""
        WITH RECURSIVE chain AS (
            SELECT id, title, origin, 0 AS depth, ',' || id || ',' AS path
            FROM nodes WHERE id = :start_id

            UNION ALL

            SELECT n.id, n.title, n.origin, c.depth + 1, c.path || n.id || ','
            FROM nodes n
            JOIN edges e ON e.from_id = n.id
            JOIN chain c ON e.to_id = c.id
            WHERE e.edge_type = 'source'
              AND c.depth < :max_depth
              AND instr(c.path, ',' || n.id || ',') = 0
        )
        SELECT DISTINCT id, title, origin, depth FROM chain WHERE id != :start_id ORDER BY depth
    """, {"start_id": node_id, "max_depth": max_depth}).fetchall()

    return [{"id": r["id"], "title": r["title"], "origin": r["origin"], "depth": r["depth"]} for r in rows]


def get_neighborhood(conn, node_id: str, radius: int = 2) -> list[NodeSummary]:
    """Get nodes within N hops (all edge types)."""
    rows = conn.execute("""
        WITH RECURSIVE nbr AS (
            SELECT id, title, origin, created_at, updated_at,
                   published_at, published_at_start, published_at_precision,
                   file_path, body, 0 AS depth, ',' || id || ',' AS path
            FROM nodes WHERE id = :start_id

            UNION ALL

            SELECT n.id, n.title, n.origin, n.created_at, n.updated_at,
                   n.published_at, n.published_at_start, n.published_at_precision,
                   n.file_path, n.body,
                   nb.depth + 1, nb.path || n.id || ','
            FROM nodes n
            JOIN edges e ON (e.to_id = n.id AND e.from_id = nb.id)
                         OR (e.from_id = n.id AND e.to_id = nb.id)
            JOIN nbr nb ON TRUE
            WHERE nb.depth < :radius
              AND instr(nb.path, ',' || n.id || ',') = 0
        )
        SELECT DISTINCT id, title, origin, created_at, updated_at,
               published_at, published_at_start, published_at_precision,
               file_path, body
        FROM nbr WHERE id != :start_id
    """, {"start_id": node_id, "radius": radius}).fetchall()

    return [_row_to_summary(r) for r in rows]


# ── Staleness detection ───────────────────────────────────────────────

def get_stale_nodes(conn) -> list[dict]:
    """Find pages with outgoing source edges whose sources have been updated."""
    rows = conn.execute("""
        SELECT
            c.id AS concept_id,
            c.title AS concept_title,
            c.updated_at AS concept_updated,
            COUNT(s.id) AS updated_source_count,
            GROUP_CONCAT(s.title, ', ') AS updated_source_titles
        FROM nodes c
        JOIN edges e ON e.from_id = c.id AND e.edge_type = 'source'
        JOIN nodes s ON s.id = e.to_id AND s.updated_at > c.updated_at
        WHERE EXISTS (SELECT 1 FROM edges WHERE from_id = c.id AND edge_type = 'source')
        GROUP BY c.id
        HAVING updated_source_count > 0
    """).fetchall()

    return [dict(r) for r in rows]


def detect_new_sources(
    conn,
    concept_id: str,
    embedding_provider: EmbeddingProvider | None = None,
    distance_threshold: float = 0.35,
) -> list[NodeSummary]:
    """Find pages related to a concept but not yet in its sources.

    Two detection methods:
    1. Semantic similarity — hybrid search on concept body, filtered by distance and recency.
    2. Reverse related edges — pages that explicitly declared related: [[this concept]].
       These bypass the timestamp/distance filters since the user declared the relationship.
    """
    concept = conn.execute("SELECT * FROM nodes WHERE id = ?", (concept_id,)).fetchone()
    if not concept:
        return []

    known_source_ids = {
        r["to_id"]
        for r in conn.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'source'",
            (concept_id,),
        )
    }

    # Use concept body for richer query
    query_text = concept["body"][:2000]

    if embedding_provider:
        hits = hybrid_search(conn, query_text, limit=20, embedding_provider=embedding_provider)
    else:
        hits = fts_search(conn, query_text, limit=20)

    meta_pages = {"index", "log", "hot"}
    new_sources = []
    for hit in hits:
        if (
            hit.node_id not in known_source_ids
            and hit.node_id != concept_id
            and hit.node_id not in meta_pages
            and hit.updated_at > concept["updated_at"]
        ):
            if embedding_provider and hit.vec_distance is not None:
                if hit.vec_distance >= distance_threshold:
                    continue  # Too distant
            new_sources.append(NodeSummary(
                id=hit.node_id, title=hit.title, origin=hit.origin,
                updated_at=hit.updated_at,
                created_at=hit.created_at,
                published_at=hit.published_at,
                published_at_start=hit.published_at_start,
                published_at_precision=hit.published_at_precision,
                snippet=hit.snippet,
            ))

    # Also surface pages that explicitly declared related: [[this concept]]
    # These bypass timestamp/distance filters — the user's declaration is the signal.
    seen_ids = {s.id for s in new_sources} | known_source_ids | {concept_id} | meta_pages
    reverse_related = conn.execute(
        f"SELECT {_NODE_VIEW_COLS} "
        "FROM edges e JOIN nodes n ON e.from_id = n.id "
        "WHERE e.to_id = ? AND e.edge_type = 'related'",
        (concept_id,),
    ).fetchall()
    for row in reverse_related:
        if row["id"] not in seen_ids:
            new_sources.append(_row_to_summary(row))
            seen_ids.add(row["id"])

    return new_sources


# ── Explore ───────────────────────────────────────────────────────────

def explore(
    conn,
    topic: str,
    embedding_provider: EmbeddingProvider | None = None,
) -> ExploreResult:
    """Interactive exploration: find synthesis page, check staleness, suggest actions."""
    result = ExploreResult(topic=topic)

    # Search for the topic
    search_hits = hybrid_search(conn, topic, limit=10, embedding_provider=embedding_provider)
    result.search_results = search_hits

    # Find the best hub candidate by graph structure (outgoing source edges)
    synthesis_node = None
    best_score = -1.0
    for hit in search_hits:
        src_count = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE from_id = ? AND edge_type = 'source'",
            (hit.node_id,),
        ).fetchone()[0]

        score = hit.score
        if src_count > 0:
            score += min(src_count, 5) * 0.05

        if score > best_score and src_count > 0:
            best_score = score
            synthesis_node = get_node_summary(conn, hit.node_id)

    if synthesis_node:
        result.hub = synthesis_node

        # Days since update
        try:
            updated_date = datetime.strptime(synthesis_node.updated_at, "%Y-%m-%d").date()
            result.days_since_update = (date.today() - updated_date).days
        except (ValueError, TypeError):
            pass

        # Staleness: check if known sources were updated
        stale_sources = []
        source_edges = conn.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'source'",
            (synthesis_node.id,),
        ).fetchall()
        for edge in source_edges:
            source = conn.execute(
                f"SELECT {_NODE_VIEW_COLS} FROM nodes n "
                "WHERE n.id = ? AND n.updated_at > ?",
                (edge["to_id"], synthesis_node.updated_at),
            ).fetchone()
            if source:
                stale_sources.append(_row_to_summary(source))

        result.stale_sources = stale_sources

        # New unincorporated sources
        new_sources = detect_new_sources(conn, synthesis_node.id, embedding_provider)
        result.unincorporated_sources = new_sources

        result.is_stale = bool(stale_sources) or bool(new_sources)

        # Graph context
        source_chain = get_source_chain(conn, synthesis_node.id)
        result.source_chain = [
            NodeSummary(id=s["id"], title=s["title"], origin=s["origin"],
                       updated_at="")
            for s in source_chain if s["id"] != synthesis_node.id
        ]

        derived = get_derived_pages(conn, synthesis_node.id)
        result.derived_pages = [
            NodeSummary(id=d["id"], title=d["title"], origin=d["origin"],
                       updated_at="")
            for d in derived
        ]

        # Adjacent topics
        result.adjacent_topics = get_neighborhood(conn, synthesis_node.id, radius=2)

        # Suggested actions
        if stale_sources:
            titles = ", ".join(s.title for s in stale_sources[:3])
            result.suggested_actions.append(
                f"Recompile [[{synthesis_node.id}]] — {len(stale_sources)} source(s) updated: {titles}"
            )
        if new_sources:
            titles = ", ".join(s.title for s in new_sources[:3])
            result.suggested_actions.append(
                f"Incorporate {len(new_sources)} new source(s) into [[{synthesis_node.id}]]: {titles}"
            )
        if not stale_sources and not new_sources:
            result.suggested_actions.append(f"[[{synthesis_node.id}]] is up to date.")
        if result.adjacent_topics:
            adj = result.adjacent_topics[0]
            result.suggested_actions.append(f"Explore adjacent topic: [[{adj.id}]]")
    else:
        # No hub page found
        if search_hits:
            result.suggested_actions.append(
                f"No hub page for '{topic}'. Create one from {len(search_hits)} related pages?"
            )
        else:
            result.suggested_actions.append(
                f"No content found for '{topic}'. Add sources first."
            )

    return result


# ── List / index health ───────────────────────────────────────────────

def list_nodes(
    conn,
    origin_filter: str | None = None,
    tag_filter: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    published_after: str | None = None,
    published_before: str | None = None,
    sort: str = "updated_at",
    limit: int = 50,
) -> list[NodeSummary]:
    """Filtered/sorted listing of nodes.

    Date params expect pre-validated YYYY-MM-DD strings. See `_build_date_predicates`
    for filter semantics (overlap on published_at_start/_end).
    """
    sql = f"SELECT DISTINCT {_NODE_VIEW_COLS} FROM nodes n"
    conditions = []
    params: list = []

    if tag_filter:
        sql += " JOIN tags t ON t.node_id = n.id"
        conditions.append("t.tag = ?")
        params.append(tag_filter)

    if origin_filter:
        conditions.append("n.origin = ?")
        params.append(origin_filter)

    date_clauses, date_params = _build_date_predicates({
        "created_after": created_after,
        "created_before": created_before,
        "published_after": published_after,
        "published_before": published_before,
    })
    if date_clauses:
        conditions.append(date_clauses)
        params.extend(date_params)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sort_col = {
        "updated_at": "n.updated_at",
        "created_at": "n.created_at",
        "published_at": "n.published_at_start",  # sort by interval start
        "title": "n.title",
    }.get(sort, "n.updated_at")
    sql += f" ORDER BY {sort_col} DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_summary(r) for r in rows]


def get_status(conn) -> StatusResult:
    """Index health summary."""
    node_count = conn.execute("SELECT COUNT(*) as cnt FROM nodes").fetchone()["cnt"]
    edge_count = conn.execute("SELECT COUNT(*) as cnt FROM edges").fetchone()["cnt"]
    chunk_count = conn.execute("SELECT COUNT(*) as cnt FROM chunks").fetchone()["cnt"]

    # Count embedded chunks
    embedded = conn.execute("""
        SELECT COUNT(*) as cnt FROM chunks c
        JOIN chunks_vec cv ON c.chunk_id = cv.rowid
    """).fetchone()["cnt"]

    # Orphan chunks (in chunks but not in chunks_vec)
    orphans = conn.execute("""
        SELECT COUNT(*) as cnt FROM chunks c
        LEFT JOIN chunks_vec cv ON c.chunk_id = cv.rowid
        WHERE cv.rowid IS NULL
    """).fetchone()["cnt"]

    # Stale count
    stale = len(get_stale_nodes(conn))

    # Origin distribution
    origins = {}
    for row in conn.execute("SELECT origin, COUNT(*) as cnt FROM nodes GROUP BY origin"):
        origins[row["origin"]] = row["cnt"]

    coverage = embedded / chunk_count if chunk_count > 0 else 0.0

    return StatusResult(
        node_count=node_count,
        edge_count=edge_count,
        chunk_count=chunk_count,
        embedded_chunks=embedded,
        embedding_coverage=coverage,
        stale_count=stale,
        orphan_chunks=orphans,
        origins=origins,
    )
