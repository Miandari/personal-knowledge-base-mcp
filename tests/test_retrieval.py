"""Retrieval quality tests.

Parametrized over fixtures/retrieval_cases.yaml. Runs each query against
multiple qmd modes and checks that expected pages appear in the top-k.
"""

import pytest
from lib.qmd_client import qmd_query, precision_at_k, mrr


# Modes to test. Starts with the cheapest (BM25) and escalates.
QMD_MODES = ["bm25", "hybrid_no_rerank"]
# Add "hybrid" and "vector" once reranker model is downloaded and warm.
# QMD_MODES = ["bm25", "vector", "hybrid_no_rerank", "hybrid"]


@pytest.fixture(scope="session")
def qmd_col(qmd_collection):
    return qmd_collection


class TestRetrieval:
    """Run each retrieval case across qmd modes."""

    @pytest.mark.parametrize("mode", QMD_MODES)
    def test_must_appear_in_top_k(self, retrieval_cases, qmd_col, mode):
        """Every case's must_appear_in_top pages should be found in top-k."""
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
            pytest.fail(
                f"{len(failures)} retrieval failure(s):\n" + "\n".join(failures)
            )

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
        assert avg >= 0.7, (
            f"[{mode}] Average precision@k = {avg:.2f} (need >= 0.70). "
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
        assert avg >= 0.5, (
            f"[{mode}] Average MRR = {avg:.2f} (need >= 0.50). "
            f"Per-case: {[f'{v:.2f}' for v in mrr_values]}"
        )
