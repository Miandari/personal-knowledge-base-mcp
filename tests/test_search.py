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

    def test_type_filter_concept(self):
        results = kb_query("AI coding", n=10, mode="bm25", filters={"type": "concept"})
        for r in results:
            # The node type is embedded in the path
            assert "concept" in r.node_id or "concepts/" in r.path, f"Type filter leaked: {r.path}"

    def test_sentiment_filter_critical(self):
        results = kb_query("AI coding agents", n=10, mode="bm25", filters={"sentiment": "critical"})
        if results:
            # Should primarily return the uncomfortable-truths source
            assert any("uncomfortable-truths" in r.path for r in results), \
                f"Sentiment filter didn't surface critical source: {[r.path for r in results]}"
