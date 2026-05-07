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

from pkb import config
from pkb.db import get_connection, init_schema
from pkb.server import kb_find, kb_save, kb_status


@pytest.fixture(autouse=True)
def _require_db():
    """Skip all tests if no database exists."""
    if not config.DB_PATH.exists():
        pytest.skip("No live database. Run `python -m pkb rebuild` first.")


class TestKbFindSearch:
    """kb_find search mode tests."""

    def test_basic_search(self):
        results = kb_find(query="AI coding agents", limit=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert "node_id" in results[0]
        assert "title" in results[0]
        assert "score" in results[0]

    def test_bm25_mode(self):
        results = kb_find(query="AI coding agents", limit=5, mode="bm25")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_origin_filter(self):
        results = kb_find(query="AI", limit=10, origin="note")
        for r in results:
            assert r["origin"] == "note"

    def test_empty_query(self):
        results = kb_find(query="", limit=5)
        assert isinstance(results, list)


class TestKbFindGet:
    """kb_find get mode tests."""

    def test_get_existing_page(self):
        result = kb_find(id="ai-coding-agents")
        assert result is not None
        assert result["title"] == "AI coding agents"
        assert result["origin"] == "note"
        assert len(result["body"]) > 100

    def test_get_with_edges(self):
        result = kb_find(id="ai-coding-agents")
        assert "sources" in result
        assert "related" in result
        assert "sourced_by" in result
        assert isinstance(result["sources"], list)

    def test_get_nonexistent(self):
        result = kb_find(id="nonexistent-page")
        assert result is None


class TestKbFindList:
    """kb_find list mode tests."""

    def test_list_by_origin(self):
        results = kb_find(origin="note")
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(r["origin"] == "note" for r in results)

    def test_list_sorted(self):
        results = kb_find(origin="note", sort="title")
        assert isinstance(results, list)


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


class TestKbSaveCreate:
    """kb_save create mode — uses a temporary page that gets cleaned up."""

    def test_creates_file(self):
        result = kb_save(
            title="Test MCP Add Page",
            origin="webpage",
            body="# Test\n\nThis is a test page created by test_mcp_server.py.",
            tags=["test", "automated"],
        )

        assert "error" not in result, f"kb_save returned error: {result}"

        expected_path = config.WIKI_DIR / "test-mcp-add-page.md"
        try:
            assert expected_path.exists(), f"File not created at {expected_path}"

            from pkb.search import get_node_summary
            conn = get_connection()
            try:
                summary = get_node_summary(conn, "test-mcp-add-page")
                assert summary is not None
            finally:
                conn.close()
        finally:
            if expected_path.exists():
                expected_path.unlink()
            conn = get_connection()
            try:
                conn.execute("DELETE FROM nodes_fts WHERE node_id = 'test-mcp-add-page'")
                conn.execute("DELETE FROM nodes WHERE id = 'test-mcp-add-page'")
                conn.commit()
            finally:
                conn.close()

    def test_conflict(self):
        result = kb_save(
            title="AI coding agents",
            origin="note",
            body="Duplicate.",
        )
        assert "error" in result or "already exists" in str(result).lower()


class TestKbSaveReindex:
    """kb_save reindex mode (id only)."""

    def test_reindex_existing_page(self):
        result = kb_save(id="ai-coding-agents")
        assert "error" not in result, f"Reindex failed: {result}"

    def test_reindex_nonexistent(self):
        result = kb_save(id="nonexistent-page")
        assert "error" in result
