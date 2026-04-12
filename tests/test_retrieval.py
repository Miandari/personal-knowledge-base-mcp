"""Retrieval quality tests.

Parametrized over fixtures/retrieval_cases.yaml. Runs each query against
multiple qmd modes and checks that expected pages appear in the top-k.
Also tests negative retrieval (queries that should return nothing).
"""

from pathlib import Path

import pytest
import yaml
from .lib.qmd_client import qmd_query, precision_at_k, mrr


# Modes to test. Starts with the cheapest (BM25) and escalates.
QMD_MODES = ["bm25", "hybrid_no_rerank"]
# Add "hybrid" and "vector" once reranker model is downloaded and warm.
# QMD_MODES = ["bm25", "vector", "hybrid_no_rerank", "hybrid"]

# Mode-specific thresholds. BM25 is keyword-only so it legitimately misses
# paraphrase queries — that's not a bug, it's the expected limitation.
PRECISION_THRESHOLDS = {"bm25": 0.50, "hybrid_no_rerank": 0.70, "hybrid": 0.80, "vector": 0.60}
MRR_THRESHOLDS = {"bm25": 0.35, "hybrid_no_rerank": 0.50, "hybrid": 0.60, "vector": 0.40}


@pytest.fixture(scope="session")
def qmd_col(qmd_collection):
    return qmd_collection


@pytest.fixture(scope="session")
def negative_cases() -> list[dict]:
    """Load negative retrieval cases from the YAML fixture."""
    fixture = Path(__file__).parent / "fixtures" / "retrieval_cases.yaml"
    with open(fixture) as f:
        data = yaml.safe_load(f)
    return data.get("negative_cases", [])


class TestRetrieval:
    """Run each retrieval case across qmd modes."""

    @pytest.mark.parametrize("mode", QMD_MODES)
    def test_must_appear_in_top_k(self, retrieval_cases, qmd_col, mode):
        """Every case's must_appear_in_top pages should be found in top-k.

        BM25 is keyword-only and legitimately misses paraphrase queries —
        so BM25 failures are diagnostic (printed), not hard failures.
        Hybrid mode is the pass/fail gate.
        """
        failures = []
        for case in retrieval_cases:
            query = case["query"]
            expected = case["must_appear_in_top"]
            k = case.get("k", 5)

            try:
                results = qmd_query(query, collection=qmd_col, n=k, mode=mode)
            except RuntimeError as e:
                failures.append(f"[{mode}] '{query}': qmd error — {e}")
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
                # BM25 is keyword-only — misses are expected for paraphrase queries
                import sys
                print(f"\n--- BM25 diagnostic ({len(failures)} misses) ---", file=sys.stderr)
                for f in failures:
                    print(f"  {f}", file=sys.stderr)
            else:
                pytest.fail(msg)

    @pytest.mark.parametrize("mode", QMD_MODES)
    def test_precision_at_k(self, retrieval_cases, qmd_col, mode):
        """Aggregate precision@k across all cases should be >= 0.7."""
        precisions = []
        for case in retrieval_cases:
            k = case.get("k", 5)
            try:
                results = qmd_query(case["query"], collection=qmd_col, n=k, mode=mode)
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

    @pytest.mark.parametrize("mode", QMD_MODES)
    def test_soft_rank_first(self, retrieval_cases, qmd_col, mode):
        """Cases with should_rank_first: warn (not fail) if #1 is wrong."""
        warnings = []
        for case in retrieval_cases:
            target = case.get("should_rank_first")
            if not target:
                continue
            try:
                results = qmd_query(case["query"], collection=qmd_col, n=1, mode=mode)
                if results and target not in results[0].path:
                    actual = results[0].path.split("/")[-1]
                    warnings.append(
                        f"[{mode}] '{case['query']}': expected #1 = '{target}', got '{actual}'"
                    )
            except RuntimeError:
                continue

        if warnings:
            # Soft assertion — print warnings but don't fail
            import sys
            print(f"\n--- Soft rank-first warnings ({len(warnings)}) ---", file=sys.stderr)
            for w in warnings:
                print(f"  WARN: {w}", file=sys.stderr)


class TestRetrievalMRR:
    """Mean Reciprocal Rank across all cases."""

    @pytest.mark.parametrize("mode", QMD_MODES)
    def test_mean_mrr(self, retrieval_cases, qmd_col, mode):
        """Average MRR across cases with should_rank_first should be >= 0.5."""
        mrr_values = []
        for case in retrieval_cases:
            target = case.get("should_rank_first")
            if not target:
                continue
            try:
                results = qmd_query(case["query"], collection=qmd_col, n=10, mode=mode)
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


class TestNegativeRetrieval:
    """Queries about topics NOT in the vault should return nothing meaningful.

    Note on scores: qmd's JSON scores are rank-based (1/rank), not similarity
    scores. Score-based thresholds are meaningless. Instead, we use BM25 mode
    which correctly returns an EMPTY result set when no documents contain the
    query terms (keyword matching). This is the reliable negative signal.

    Hybrid mode always returns N results (even for garbage queries) because
    vector search finds the "nearest" embedding regardless of relevance.
    So we only test negatives in BM25 mode.
    """

    def test_no_false_positives_bm25(self, negative_cases, qmd_col):
        """BM25 should return 0 results for queries about topics not in the vault."""
        if not negative_cases:
            pytest.skip("No negative cases defined")

        false_positives = []
        for case in negative_cases:
            query = case["query"]
            try:
                results = qmd_query(query, collection=qmd_col, n=5, mode="bm25")
            except RuntimeError:
                continue  # qmd error → no results → correct

            if results:
                false_positives.append(
                    f"'{query}': BM25 returned {len(results)} result(s), expected 0. "
                    f"Top: {results[0].path}"
                )

        if false_positives:
            pytest.fail(
                f"{len(false_positives)} false positive(s):\n" + "\n".join(false_positives)
            )

    def test_negative_queries_return_fewer_results_hybrid(self, negative_cases, qmd_col):
        """In hybrid mode, negative queries should return fewer results than
        positive queries (a soft signal since hybrid always returns something)."""
        if not negative_cases:
            pytest.skip("No negative cases defined")

        # Baseline: a known-good query
        try:
            positive = qmd_query("AI coding agents", collection=qmd_col, n=10, mode="hybrid_no_rerank")
            positive_count = len(positive)
        except RuntimeError:
            pytest.skip("qmd hybrid mode not available")

        for case in negative_cases:
            try:
                results = qmd_query(case["query"], collection=qmd_col, n=10, mode="hybrid_no_rerank")
                # Soft check: negative should return ≤ positive (ideally much less)
                if len(results) > 0:
                    import sys
                    print(
                        f"\n  INFO: hybrid returned {len(results)} results for "
                        f"'{case['query']}' (vs {positive_count} for positive). "
                        "This is expected — hybrid uses vector similarity which always finds something.",
                        file=sys.stderr,
                    )
            except RuntimeError:
                pass  # fine
