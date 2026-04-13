"""Thin wrapper around the kb package for use in tests.

Replaces qmd_client.py — same interface shape, backed by SQLite.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

# Add project root to path so we can import kb
import sys
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pkb.db import get_connection, init_schema
from pkb.search import hybrid_search, fts_search, get_node, get_status
from pkb.embeddings import get_provider
from pkb import config


@dataclass
class KbResult:
    """Search result matching the interface shape of QmdResult."""
    title: str
    path: str       # wiki-relative path, e.g. "concepts/ai-coding-agents.md"
    node_id: str
    score: float
    vec_distance: float | None
    snippet: str

    @property
    def file(self) -> str:
        """Compatibility with code that checks .file"""
        return self.path


def _ensure_db() -> sqlite3.Connection:
    """Get a connection to the live DB, fail if it doesn't exist."""
    if not config.DB_PATH.exists():
        raise RuntimeError(
            f"No database at {config.DB_PATH}. Run `python -m pkb rebuild` first."
        )
    return get_connection()


def kb_query(
    query: str,
    n: int = 10,
    mode: str = "hybrid",
    filters: dict | None = None,
) -> list[KbResult]:
    """Run a search and return parsed results.

    mode: "hybrid" (FTS5 + vec + RRF), "bm25" (FTS5 only),
          "hybrid_no_rerank" (alias for "hybrid" — no reranker in this system)
    """
    conn = _ensure_db()
    filters = filters or {}

    try:
        if mode in ("bm25",):
            results = fts_search(conn, query, limit=n, filters=filters)
        else:
            # hybrid and hybrid_no_rerank both map to the same hybrid search
            provider = get_provider(config.EMBEDDING_PROVIDER, conn=conn)
            results = hybrid_search(conn, query, limit=n, filters=filters, embedding_provider=provider)

        return [
            KbResult(
                title=r.title,
                path=_node_id_to_path(r.node_id),
                node_id=r.node_id,
                score=r.score,
                vec_distance=r.vec_distance,
                snippet=r.snippet,
            )
            for r in results
        ]
    finally:
        conn.close()


def kb_get(node_id: str) -> str:
    """Fetch a single document's full content."""
    conn = _ensure_db()
    try:
        detail = get_node(conn, node_id)
        if detail:
            return detail.body
        # Try path-based lookup
        node_id_clean = node_id.lstrip("#")
        if node_id_clean.endswith(".md"):
            node_id_clean = node_id_clean[:-3]
        detail = get_node(conn, node_id_clean)
        return detail.body if detail else ""
    finally:
        conn.close()


def kb_status() -> dict:
    """Return index health info."""
    conn = _ensure_db()
    try:
        status = get_status(conn)
        return status.model_dump()
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def precision_at_k(results: list[KbResult], expected_paths: list[str], k: int = 5) -> float:
    """Fraction of expected paths found in the top-k results."""
    top_k_paths = {r.path for r in results[:k]}
    found = sum(1 for p in expected_paths if any(p in tp for tp in top_k_paths))
    return found / len(expected_paths) if expected_paths else 0.0


def mrr(results: list[KbResult], target_path: str) -> float:
    """Mean Reciprocal Rank: 1/(rank of first result containing target_path), or 0."""
    for i, r in enumerate(results):
        if target_path in r.path:
            return 1.0 / (i + 1)
    return 0.0


def _node_id_to_path(node_id: str) -> str:
    """Convert a node ID to a wiki-relative path.

    "concepts/ai-coding-agents" → "concepts/ai-coding-agents.md"
    """
    if not node_id.endswith(".md"):
        return node_id + ".md"
    return node_id
