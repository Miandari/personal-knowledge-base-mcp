"""MCP server tool interface tests.

Tests each MCP tool in isolation to verify input/output contracts.
Runs against the live database.
"""

import tempfile
from pathlib import Path

import pytest

import sys
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from kb import config
from kb.db import get_connection, init_schema
from kb.server import (
    kb_search, kb_explore, kb_get, kb_list,
    kb_add, kb_synthesize, kb_reindex, kb_status,
)


@pytest.fixture(autouse=True)
def _require_db():
    """Skip all tests if no database exists."""
    if not config.DB_PATH.exists():
        pytest.skip("No live database. Run `python -m kb rebuild` first.")


class TestKbSearch:
    """kb_search tool tests."""

    def test_basic_search(self):
        results = kb_search(query="AI coding agents", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert "node_id" in results[0]
        assert "title" in results[0]
        assert "score" in results[0]

    def test_bm25_mode(self):
        results = kb_search(query="AI coding agents", limit=5, mode="bm25")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_type_filter(self):
        results = kb_search(query="AI", limit=10, type="concept")
        for r in results:
            assert r["type"] == "concept"

    def test_empty_query(self):
        results = kb_search(query="", limit=5)
        assert isinstance(results, list)


class TestKbExplore:
    """kb_explore tool tests."""

    def test_explore_known_topic(self):
        result = kb_explore(topic="AI coding agents")
        assert isinstance(result, dict)
        assert result["topic"] == "AI coding agents"
        assert "is_stale" in result
        assert "suggested_actions" in result
        assert isinstance(result["suggested_actions"], list)

    def test_explore_returns_synthesis(self):
        result = kb_explore(topic="AI coding agents")
        if result.get("synthesis"):
            assert "id" in result["synthesis"]
            assert "title" in result["synthesis"]

    def test_explore_unknown_topic(self):
        result = kb_explore(topic="underwater basket weaving techniques")
        assert isinstance(result, dict)
        assert len(result["suggested_actions"]) > 0


class TestKbGet:
    """kb_get tool tests."""

    def test_get_existing_page(self):
        result = kb_get(node_id="concepts/ai-coding-agents")
        assert result is not None
        assert result["title"] == "AI coding agents"
        assert result["type"] == "concept"
        assert len(result["body"]) > 100

    def test_get_with_edges(self):
        result = kb_get(node_id="concepts/ai-coding-agents")
        assert "sources" in result
        assert "related" in result
        assert "sourced_by" in result
        assert isinstance(result["sources"], list)

    def test_get_nonexistent(self):
        result = kb_get(node_id="nonexistent/page")
        assert result is None


class TestKbList:
    """kb_list tool tests."""

    def test_list_all(self):
        results = kb_list()
        assert isinstance(results, list)
        assert len(results) > 0

    def test_list_by_type(self):
        results = kb_list(type="concept")
        assert all(r["type"] == "concept" for r in results)

    def test_list_sorted(self):
        results = kb_list(sort="title")
        assert isinstance(results, list)


class TestKbSynthesize:
    """kb_synthesize tool tests."""

    def test_synthesize_returns_prompt(self):
        result = kb_synthesize(
            node_id="concepts/ai-coding-agents",
            source_ids=["sources/uncomfortable-truths-ai-coding-agents"],
        )
        assert isinstance(result, str)
        assert "Synthesis task" in result
        assert "ai-coding-agents" in result
        assert "Rules" in result

    def test_synthesize_includes_sources(self):
        result = kb_synthesize(
            node_id="concepts/ai-coding-agents",
            source_ids=["sources/uncomfortable-truths-ai-coding-agents"],
        )
        assert "uncomfortable-truths" in result.lower() or "uncomfortable truths" in result.lower()


class TestKbStatus:
    """kb_status tool tests."""

    def test_status_structure(self):
        result = kb_status()
        assert isinstance(result, dict)
        assert "node_count" in result
        assert "edge_count" in result
        assert "chunk_count" in result
        assert "embedded_chunks" in result
        assert "embedding_coverage" in result
        assert result["node_count"] > 0


class TestKbAdd:
    """kb_add tool tests — uses a temporary page that gets cleaned up."""

    def test_add_creates_file(self):
        """Add a page, verify it exists, then clean up."""
        result = kb_add(
            title="Test MCP Add Page",
            type="source",
            body="# Test\n\nThis is a test page created by test_mcp_server.py.",
            tags=["test", "automated"],
        )

        # Check result
        assert "error" not in result, f"kb_add returned error: {result}"

        # Verify file was created
        expected_path = config.WIKI_DIR / "sources" / "test-mcp-add-page.md"
        try:
            assert expected_path.exists(), f"File not created at {expected_path}"

            # Verify it's indexed
            from kb.search import get_node_summary
            conn = get_connection()
            try:
                summary = get_node_summary(conn, "sources/test-mcp-add-page")
                assert summary is not None
            finally:
                conn.close()
        finally:
            # Clean up: delete the test file
            if expected_path.exists():
                expected_path.unlink()
            # Clean up DB entry
            conn = get_connection()
            try:
                conn.execute("DELETE FROM nodes_fts WHERE node_id = 'sources/test-mcp-add-page'")
                conn.execute("DELETE FROM nodes WHERE id = 'sources/test-mcp-add-page'")
                conn.commit()
            finally:
                conn.close()

    def test_add_conflict(self):
        """Adding a page that already exists should return an error."""
        result = kb_add(
            title="AI coding agents",
            type="concept",
            body="Duplicate.",
        )
        assert "error" in result or "already exists" in str(result).lower()


class TestKbReindex:
    """kb_reindex tool tests."""

    def test_reindex_existing_page(self):
        result = kb_reindex(node_id="concepts/ai-coding-agents")
        assert "error" not in result, f"Reindex failed: {result}"

    def test_reindex_nonexistent(self):
        result = kb_reindex(file_path="wiki/nonexistent/page.md")
        assert "error" in result
