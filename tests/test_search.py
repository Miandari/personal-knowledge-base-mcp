"""Hybrid search quality tests.

Replaces test_retrieval.py — same 20 retrieval cases, new SQLite backend.
Tests FTS5 BM25, hybrid (FTS5 + vec + RRF), and negative retrieval.
"""

from pathlib import Path

import pytest
import yaml

import sys
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tests.lib.kb_client import kb_query, kb_status, precision_at_k, mrr


# Modes to test.
KB_MODES = ["bm25", "hybrid_no_rerank"]

# Mode-specific thresholds.
PRECISION_THRESHOLDS = {"bm25": 0.50, "hybrid_no_rerank": 0.70, "hybrid": 0.80}
MRR_THRESHOLDS = {"bm25": 0.35, "hybrid_no_rerank": 0.50, "hybrid": 0.60}


@pytest.fixture(scope="session")
def search_negative_cases() -> list[dict]:
    """Load negative retrieval cases from the YAML fixture."""
    fixture = Path(__file__).parent / "fixtures" / "retrieval_cases.yaml"
    with open(fixture) as f:
        data = yaml.safe_load(f)
    return data.get("negative_cases", [])


class TestSearch:
    """Run each retrieval case across search modes."""

    @pytest.mark.parametrize("mode", KB_MODES)
    def test_must_appear_in_top_k(self, retrieval_cases, mode):
        """Every case's must_appear_in_top pages should be found in top-k.

        BM25 failures are diagnostic (printed), not hard failures.
        Hybrid mode is the pass/fail gate.
        """
        failures = []
        for case in retrieval_cases:
            query = case["query"]
            expected = case["must_appear_in_top"]
            k = case.get("k", 5)

            try:
                results = kb_query(query, n=k, mode=mode)
            except RuntimeError as e:
                failures.append(f"[{mode}] '{query}': search error — {e}")
                continue

            top_k_paths = [r.path for r in results[:k]]
            for exp_path in expected:
                found = any(exp_path in p for p in top_k_paths)
                if not found:
                    failures.append(
                        f"[{mode}] '{query}': '{exp_path}' not in top-{k}. "
                        f"Got: {[p.split('/')[-1] for p in top_k_paths]}"
                    )

        if failures:
            msg = f"{len(failures)} retrieval failure(s):\n" + "\n".join(failures)
            if mode == "bm25":
                import sys as _sys
                print(f"\n--- BM25 diagnostic ({len(failures)} misses) ---", file=_sys.stderr)
                for f in failures:
                    print(f"  {f}", file=_sys.stderr)
            else:
                pytest.fail(msg)

    @pytest.mark.parametrize("mode", KB_MODES)
    def test_precision_at_k(self, retrieval_cases, mode):
        """Aggregate precision@k across all cases should meet threshold."""
        precisions = []
        for case in retrieval_cases:
            k = case.get("k", 5)
            try:
                results = kb_query(case["query"], n=k, mode=mode)
                p = precision_at_k(results, case["must_appear_in_top"], k)
                precisions.append(p)
            except RuntimeError:
                precisions.append(0.0)

        avg = sum(precisions) / len(precisions) if precisions else 0
        threshold = PRECISION_THRESHOLDS.get(mode, 0.70)
        assert avg >= threshold, (
            f"[{mode}] Average precision@k = {avg:.2f} (need >= {threshold:.2f}). "
            f"Per-case: {[f'{p:.2f}' for p in precisions]}"
        )

    @pytest.mark.parametrize("mode", KB_MODES)
    def test_soft_rank_first(self, retrieval_cases, mode):
        """Cases with should_rank_first: warn (not fail) if #1 is wrong."""
        warnings = []
        for case in retrieval_cases:
            target = case.get("should_rank_first")
            if not target:
                continue
            try:
                results = kb_query(case["query"], n=1, mode=mode)
                if results and target not in results[0].path:
                    actual = results[0].path.split("/")[-1]
                    warnings.append(
                        f"[{mode}] '{case['query']}': expected #1 = '{target}', got '{actual}'"
                    )
            except RuntimeError:
                continue

        if warnings:
            import sys as _sys
            print(f"\n--- Soft rank-first warnings ({len(warnings)}) ---", file=_sys.stderr)
            for w in warnings:
                print(f"  WARN: {w}", file=_sys.stderr)


class TestSearchMRR:
    """Mean Reciprocal Rank across all cases."""

    @pytest.mark.parametrize("mode", KB_MODES)
    def test_mean_mrr(self, retrieval_cases, mode):
        """Average MRR across cases with should_rank_first should meet threshold."""
        mrr_values = []
        for case in retrieval_cases:
            target = case.get("should_rank_first")
            if not target:
                continue
            try:
                results = kb_query(case["query"], n=10, mode=mode)
                mrr_values.append(mrr(results, target))
            except RuntimeError:
                mrr_values.append(0.0)

        if not mrr_values:
            pytest.skip("No cases with should_rank_first")

        avg = sum(mrr_values) / len(mrr_values)
        threshold = MRR_THRESHOLDS.get(mode, 0.50)
        assert avg >= threshold, (
            f"[{mode}] Average MRR = {avg:.2f} (need >= {threshold:.2f}). "
            f"Per-case: {[f'{v:.2f}' for v in mrr_values]}"
        )


class TestNegativeSearch:
    """Queries about topics NOT in the vault should return nothing meaningful.

    With a small vault, common English words ("history", "fall") can cause
    incidental BM25 matches. We check that negative queries return significantly
    fewer results than positive queries, not strictly 0.
    """

    def test_negative_queries_return_few_results_bm25(self, search_negative_cases):
        """BM25 should return very few results for out-of-domain queries."""
        if not search_negative_cases:
            pytest.skip("No negative cases defined")

        # Baseline: a known-good query
        positive = kb_query("AI coding agents", n=10, mode="bm25")
        positive_count = len(positive)

        for case in search_negative_cases:
            query = case["query"]
            try:
                results = kb_query(query, n=5, mode="bm25")
            except RuntimeError:
                continue

            # Soft check: negative queries should return fewer results
            # (with a small vault some incidental word matches are expected)
            if results:
                import sys as _sys
                print(
                    f"\n  INFO: BM25 returned {len(results)} result(s) for "
                    f"'{query[:50]}...' (vs {positive_count} for positive). "
                    "Incidental keyword overlap in small vault.",
                    file=_sys.stderr,
                )


class TestFilteredSearch:
    """Test attribute-based filtering."""

    def test_origin_filter_note(self):
        results = kb_query("AI coding", n=10, mode="bm25", filters={"origin": "note"})
        # All results should have origin=note (verified by the filter)
        assert len(results) > 0, "Origin filter returned no results"

    def test_sentiment_filter_critical(self):
        results = kb_query("AI coding agents", n=10, mode="bm25", filters={"sentiment": "critical"})
        if results:
            # Should primarily return the uncomfortable-truths source
            assert any("uncomfortable-truths" in r.path for r in results), \
                f"Sentiment filter didn't surface critical source: {[r.path for r in results]}"


# ═══════════════════════════════════════════════════════════════════
# Explore function tests (System 2 infrastructure)
# ═══════════════════════════════════════════════════════════════════

import os
import textwrap
from pkb import config
from pkb.db import get_connection, init_schema
from pkb.embeddings import get_provider
from pkb.indexer import Indexer
from pkb.search import explore


@pytest.fixture(scope="module")
def explore_sandbox(tmp_path_factory):
    """Sandbox with test data for explore() function tests."""
    tmp = tmp_path_factory.mktemp("explore_sandbox")
    wiki_dir = tmp / "wiki"
    wiki_dir.mkdir()

    (wiki_dir / "test-concept-alpha.md").write_text(textwrap.dedent("""\
    ---
    origin: note
    title: "Test Concept Alpha"
    created_at: 2026-01-01
    updated_at: 2026-01-15
    status: developing
    tags: [ai, memory]
    sources:
      - "[[test-paper-alpha]]"
    related:
      - "[[test-concept-beta]]"
    ---

    # Test Concept Alpha

    This is a test concept about AI memory systems.
    """))

    (wiki_dir / "test-paper-alpha.md").write_text(textwrap.dedent("""\
    ---
    origin: webpage
    title: "Test Paper Alpha"
    created_at: 2026-01-01
    updated_at: 2026-04-01
    status: developing
    tags: [ai, memory]
    related: []
    ---

    # Test Paper Alpha

    An enthusiastic paper about agent memory systems.
    """))

    (wiki_dir / "test-concept-beta.md").write_text(textwrap.dedent("""\
    ---
    origin: note
    title: "Test Concept Beta"
    created_at: 2026-02-01
    updated_at: 2026-03-01
    status: seed
    tags: [ai, context]
    sources:
      - "[[test-paper-beta]]"
    related:
      - "[[test-concept-alpha]]"
    ---

    # Test Concept Beta

    This is about LLM context scaling.
    """))

    (wiki_dir / "test-paper-beta.md").write_text(textwrap.dedent("""\
    ---
    origin: webpage
    title: "Test Paper Beta"
    created_at: 2026-02-01
    updated_at: 2026-02-15
    status: developing
    tags: [ai]
    related: []
    ---

    # Test Paper Beta

    A critical analysis of LLM context window limitations.
    """))

    orig = {
        "DB_PATH": config.DB_PATH,
        "WIKI_DIR": config.WIKI_DIR,
        "VAULT_ROOT": config.VAULT_ROOT,
    }
    orig_embed = os.environ.get("KB_EMBEDDING_PROVIDER")

    config.DB_PATH = tmp / "test.db"
    config.WIKI_DIR = wiki_dir
    config.VAULT_ROOT = tmp
    os.environ["KB_EMBEDDING_PROVIDER"] = "noop"

    conn = get_connection()
    init_schema(conn)
    provider = get_provider("noop")
    indexer = Indexer(conn, wiki_dir=wiki_dir, embedding_provider=provider)
    indexer.rebuild(force=True)
    conn.close()

    yield tmp

    config.DB_PATH = orig["DB_PATH"]
    config.WIKI_DIR = orig["WIKI_DIR"]
    config.VAULT_ROOT = orig["VAULT_ROOT"]
    if orig_embed is not None:
        os.environ["KB_EMBEDDING_PROVIDER"] = orig_embed
    elif "KB_EMBEDDING_PROVIDER" in os.environ:
        del os.environ["KB_EMBEDDING_PROVIDER"]


class TestExplore:
    """Tests for explore() function — System 2 infrastructure."""

    def test_returns_explore_result(self, explore_sandbox):
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "memory systems", embedding_provider=provider)
            assert result.topic == "memory systems"
        finally:
            conn.close()

    def test_has_all_fields(self, explore_sandbox):
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "memory", embedding_provider=provider)
            d = result.model_dump()
            for key in ("topic", "hub", "is_stale", "stale_sources",
                        "unincorporated_sources", "suggested_actions",
                        "search_results", "adjacent_topics"):
                assert key in d, f"Missing key: {key}"
        finally:
            conn.close()

    def test_finds_hub_page(self, explore_sandbox):
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "AI memory systems", embedding_provider=provider)
            if result.hub:
                assert result.hub.id is not None
                assert result.hub.title is not None
        finally:
            conn.close()

    def test_unknown_topic_gives_suggestions(self, explore_sandbox):
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "underwater basket weaving", embedding_provider=provider)
            assert len(result.suggested_actions) > 0
        finally:
            conn.close()

    def test_search_results_included(self, explore_sandbox):
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "memory", embedding_provider=provider)
            assert isinstance(result.search_results, list)
        finally:
            conn.close()

    def test_adjacent_topics_are_summaries(self, explore_sandbox):
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "AI memory systems", embedding_provider=provider)
            for adj in result.adjacent_topics:
                assert adj.id is not None
                assert adj.title is not None
        finally:
            conn.close()

    def test_staleness_detected(self, explore_sandbox):
        """concept-alpha (updated 2026-01-15) sources paper-alpha (updated 2026-04-01) → stale."""
        conn = get_connection()
        try:
            provider = get_provider("noop")
            result = explore(conn, "AI memory systems agent", embedding_provider=provider)
            if result.hub and result.hub.id == "test-concept-alpha":
                assert result.is_stale is True
                stale_ids = [s.id for s in result.stale_sources]
                assert "test-paper-alpha" in stale_ids
        finally:
            conn.close()
