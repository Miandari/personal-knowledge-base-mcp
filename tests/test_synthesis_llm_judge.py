"""Synthesis quality tests via LLM-as-judge.

For a set of queries:
1. Retrieve relevant wiki pages via qmd
2. Construct a synthesis prompt
3. Call Claude (or the configured LLM) to produce an answer
4. Call the LLM judge to rate the answer

Requires ANTHROPIC_API_KEY (or the configured judge's API key) in .env.
"""

import os

import pytest
from lib.llm_judge import get_judge, JudgeVerdict
from lib.qmd_client import qmd_query, qmd_get

# Skip the entire module if no API key is available
pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping LLM judge tests",
)

SYNTHESIS_CASES = [
    {
        "query": "What are the main criticisms of AI coding agents for production use?",
        "min_overall": 3.5,
    },
    {
        "query": "Compare the LLM-wiki pattern with traditional RAG. When should you use each?",
        "min_overall": 3.0,
    },
    {
        "query": "What is the state of agent memory infrastructure in Q2 2026?",
        "min_overall": 3.0,
    },
    {
        "query": "How does MSA achieve 100M token context with less than 9% degradation?",
        "min_overall": 3.0,
    },
]


def _synthesize_answer(query: str, collection: str = "kb") -> tuple[str, str]:
    """Retrieve pages and produce a synthesis. Returns (wiki_pages_text, answer)."""
    import anthropic

    # Retrieve
    results = qmd_query(query, collection=collection, n=5, mode="hybrid_no_rerank")
    if not results:
        return ("(no results)", "(no answer — qmd returned nothing)")

    # Fetch full pages
    pages_text = ""
    for r in results[:3]:
        try:
            content = qmd_get(r.docid or r.path)
            pages_text += f"\n\n--- {r.title} ({r.path}) ---\n{content[:3000]}"
        except RuntimeError:
            pages_text += f"\n\n--- {r.title} ({r.path}) ---\n{r.snippet}"

    # Synthesize via Claude
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=(
            "You are answering questions from a personal knowledge base wiki. "
            "Ground every claim in the provided wiki pages. "
            "Cite each page using [[Page Name]] wikilinks. "
            "If the pages don't cover something, say so explicitly."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"## Retrieved wiki pages\n{pages_text}\n\n"
                    f"## Question\n{query}\n\n"
                    "Answer concisely, citing sources with [[wikilinks]]."
                ),
            }
        ],
    )
    answer = response.content[0].text
    return (pages_text, answer)


class TestSynthesisQuality:
    """LLM-as-judge tests for synthesis answers."""

    @pytest.mark.parametrize(
        "case",
        SYNTHESIS_CASES,
        ids=[c["query"][:50] for c in SYNTHESIS_CASES],
    )
    @pytest.mark.timeout(120)
    def test_synthesis_quality(self, case, judge_fn):
        query = case["query"]
        min_score = case["min_overall"]

        wiki_pages, answer = _synthesize_answer(query)

        verdict: JudgeVerdict = judge_fn(
            question=query, wiki_pages=wiki_pages, answer=answer
        )

        # Print details for debugging (visible with pytest -s)
        print(f"\n--- Synthesis test: {query[:60]} ---")
        print(f"  Groundedness:  {verdict.groundedness}/5")
        print(f"  Citations:     {verdict.citation_correctness}/5")
        print(f"  Hallucination: {verdict.hallucination}/5")
        print(f"  Relevance:     {verdict.relevance}/5")
        print(f"  Overall:       {verdict.overall:.1f}/5")
        print(f"  Reasoning:     {verdict.reasoning}")

        assert verdict.overall >= min_score, (
            f"Synthesis quality below threshold: {verdict.overall:.1f} < {min_score}\n"
            f"Query: {query}\n"
            f"Reasoning: {verdict.reasoning}\n"
            f"Answer excerpt: {answer[:300]}..."
        )
