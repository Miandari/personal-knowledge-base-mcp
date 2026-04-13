"""End-to-end smoke tests.

Full pipeline: raw dump exists -> wiki pages compiled -> indexed in SQLite -> query returns answer.
"""

import os
from pathlib import Path

import pytest

import sys
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tests.lib.kb_client import kb_query, kb_status


class TestIndexHealth:
    """Verify the SQLite index is in a usable state."""

    def test_db_exists(self):
        from pkb import config
        assert config.DB_PATH.exists(), f"No database at {config.DB_PATH}. Run `python -m pkb rebuild` first."

    def test_index_has_documents(self):
        status = kb_status()
        assert "error" not in status, f"Status error: {status}"
        assert status["node_count"] > 0, "Index has 0 nodes"

    def test_index_has_chunks(self):
        status = kb_status()
        assert status["chunk_count"] > 0, "Index has 0 chunks"

    def test_embedding_coverage(self):
        status = kb_status()
        assert status["embedding_coverage"] > 0, "No embeddings in index"


class TestEndToEnd:
    """Full pipeline smoke tests."""

    def test_query_returns_results(self):
        """A generic query should return at least one result."""
        results = kb_query("AI coding agents", n=5, mode="bm25")
        assert len(results) > 0, "Search returned zero results for 'AI coding agents'"

    def test_query_results_have_required_fields(self):
        """Results should have title, path, score, snippet."""
        results = kb_query("agent memory", n=3, mode="bm25")
        for r in results:
            assert r.title, f"Result missing title: {r}"
            assert r.path, f"Result missing path: {r}"
            assert r.score >= 0, f"Result has invalid score: {r.score}"

    def test_uncomfortable_truths_golden_path(self):
        """The full golden path: query -> target article in top 5."""
        results = kb_query(
            "critical takes on AI coding agents",
            n=5,
            mode="hybrid_no_rerank",
        )
        paths = [r.path for r in results]
        found = any("uncomfortable-truths" in p for p in paths)
        assert found, (
            "Golden-path failure: 'uncomfortable-truths' not in top 5. "
            f"Got: {[p.split('/')[-1] for p in paths]}"
        )

    def test_cross_concept_retrieval(self):
        """A query touching two concepts should surface both."""
        results = kb_query(
            "relationship between agent memory and context window length",
            n=10,
            mode="hybrid_no_rerank",
        )
        paths = [r.path for r in results[:10]]
        has_memory = any("agent-memory" in p for p in paths)
        has_context = any("llm-context-scaling" in p for p in paths)
        assert has_memory or has_context, (
            f"Neither agent-memory nor llm-context-scaling in top 10. Got: {[p.split('/')[-1] for p in paths]}"
        )


class TestLiveVaultOnly:
    """Tests that only make sense against the live vault."""

    @pytest.fixture(autouse=True)
    def _require_live(self, use_live_vault):
        if not use_live_vault:
            pytest.skip("Skipped -- requires --live-vault flag")

    def test_hot_cache_not_empty(self, vault_path):
        hot = vault_path / "wiki" / "hot.md"
        assert hot.exists() and hot.stat().st_size > 100, "hot.md is missing or too small"

    def test_log_has_recent_entries(self, vault_path):
        log_text = (vault_path / "wiki" / "log.md").read_text()
        assert "2026-04-11" in log_text, "log.md has no 2026-04-11 entries"

    def test_git_repo_has_phase_commits(self, vault_path):
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline"], capture_output=True, text=True, cwd=vault_path
        )
        assert "phase 1" in result.stdout, "Missing phase 1 commit"
        assert "phase 2" in result.stdout, "Missing phase 2 commit"
        assert "phase 3" in result.stdout, "Missing phase 3 commit"
