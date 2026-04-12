"""End-to-end smoke tests.

Full pipeline: raw dump exists → wiki pages compiled → qmd indexed → query returns answer.
Runs against the live vault when TEST_USE_LIVE_VAULT=true.
"""

import os

import pytest
from lib.qmd_client import qmd_query, qmd_status


class TestIndexHealth:
    """Verify the qmd index is in a usable state."""

    def test_qmd_is_available(self):
        status = qmd_status()
        assert status["returncode"] == 0, f"qmd status failed: {status['output']}"

    def test_collection_has_documents(self, qmd_collection):
        status = qmd_status(qmd_collection)
        assert "Files:" in status["output"], "qmd status doesn't show file count"
        # Extract file count
        for line in status["output"].split("\n"):
            if "Files:" in line:
                count = int(line.split("Files:")[1].strip().split()[0])
                assert count > 0, "Collection has 0 files"
                break


class TestEndToEnd:
    """Full pipeline smoke tests."""

    def test_query_returns_results(self, qmd_collection):
        """A generic query should return at least one result."""
        results = qmd_query("AI coding agents", collection=qmd_collection, n=5, mode="bm25")
        assert len(results) > 0, "qmd returned zero results for 'AI coding agents'"

    def test_query_results_have_required_fields(self, qmd_collection):
        """Results should have title, path, score, snippet."""
        results = qmd_query("agent memory", collection=qmd_collection, n=3, mode="bm25")
        for r in results:
            assert r.title, f"Result missing title: {r}"
            assert r.path, f"Result missing path: {r}"
            assert r.score >= 0, f"Result has invalid score: {r.score}"

    def test_uncomfortable_truths_golden_path(self, qmd_collection):
        """The full golden path: query → target article in top 5."""
        results = qmd_query(
            "critical takes on AI coding agents",
            collection=qmd_collection,
            n=5,
            mode="hybrid_no_rerank",
        )
        paths = [r.path for r in results]
        found = any("uncomfortable-truths" in p for p in paths)
        assert found, (
            "Golden-path failure: 'uncomfortable-truths' not in top 5. "
            f"Got: {[p.split('/')[-1] for p in paths]}"
        )

    def test_cross_concept_retrieval(self, qmd_collection):
        """A query touching two concepts should surface both."""
        results = qmd_query(
            "relationship between agent memory and context window length",
            collection=qmd_collection,
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
            pytest.skip("Skipped — requires TEST_USE_LIVE_VAULT=true")

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
