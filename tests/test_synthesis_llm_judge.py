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
from .lib.llm_judge import get_judge, JudgeVerdict
from .lib.qmd_client import qmd_query, qmd_get

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


class TestMultiSourceSynthesis:
    """Test that cross-briefing synthesis actually works.

    The key question: did wiki compilation create cross-referenced pages
    that enable synthesis across multiple briefings, or did each briefing
    become an isolated silo?
    """

    @pytest.mark.timeout(120)
    def test_cross_briefing_overview(self, judge_fn):
        """Ask for an overview across all briefings. The answer should
        reference multiple briefings, mention multiple tools, and cover
        multiple sub-topics."""
        query = (
            "Summarize what I've learned about AI agent infrastructure "
            "in the last two weeks"
        )
        wiki_pages, answer = _synthesize_answer(query)

        # ── LLM judge: standard quality check ──
        verdict = judge_fn(question=query, wiki_pages=wiki_pages, answer=answer)
        print(f"\n--- Multi-source synthesis ---")
        print(f"  Overall: {verdict.overall:.1f}/5  |  {verdict.reasoning}")

        assert verdict.overall >= 3.0, (
            f"Multi-source synthesis quality: {verdict.overall:.1f} < 3.0\n"
            f"Reasoning: {verdict.reasoning}"
        )

        # ── Programmatic breadth checks ──
        import re
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", answer)
        unique_links = set(wikilinks)

        # Should cite at least 3 different wiki pages
        assert len(unique_links) >= 3, (
            f"Expected ≥3 unique [[wikilinks]], got {len(unique_links)}: {unique_links}. "
            "This suggests the synthesis is pulling from a single page, not cross-referencing."
        )

        # Should mention at least 2 different tools/repos/products by name
        # (with 13 wiki pages and a broad overview query, 2 is realistic)
        tool_keywords = [
            "mempalace", "superpowers", "claude-obsidian", "codesight",
            "caveman", "openclaude", "memoriki", "qmd", "dapr",
            "jetbrains central", "agentguard", "agentmint", "crewai",
            "openharness", "memento-skills", "atlas", "second-brain",
            "memento", "mcp", "obra",
        ]
        mentioned = [kw for kw in tool_keywords if kw.lower() in answer.lower()]
        assert len(mentioned) >= 2, (
            f"Expected ≥2 tools/repos mentioned, got {len(mentioned)}: {mentioned}. "
            "The synthesis may be too narrow."
        )

        # Should cover multiple sub-topics (check for topic marker words)
        subtopic_markers = {
            "memory": ["memory", "mempalace", "persistent", "knowledge base"],
            "mcp": ["mcp", "protocol", "model context protocol"],
            "context": ["context window", "context scaling", "kv cache", "turboquant", "msa"],
            "skills": ["skill", "superpowers", "skill.md", "memento"],
        }
        topics_covered = []
        answer_lower = answer.lower()
        for topic, markers in subtopic_markers.items():
            if any(m in answer_lower for m in markers):
                topics_covered.append(topic)

        assert len(topics_covered) >= 2, (
            f"Expected ≥2 sub-topics covered, got {len(topics_covered)}: {topics_covered}. "
            "The synthesis may be a single-topic answer dressed as an overview."
        )
        print(f"  Breadth: {len(unique_links)} wikilinks, {len(mentioned)} tools, {len(topics_covered)} sub-topics")


class TestSingleArticleSummary:
    """Test that the system can summarize a specific known article.

    The opposite of multi-source: can it zoom in on ONE source, give a
    faithful summary, and not contaminate it with unrelated content?
    """

    @pytest.mark.timeout(120)
    def test_summarize_uncomfortable_truths(self, judge_fn):
        """Ask for a summary of the specific standupforme.app article."""
        query = (
            "Summarize the article 'Some uncomfortable truths about AI coding agents' "
            "from standupforme.app"
        )
        wiki_pages, answer = _synthesize_answer(query)

        # ── LLM judge ──
        verdict = judge_fn(question=query, wiki_pages=wiki_pages, answer=answer)
        print(f"\n--- Single-article summary ---")
        print(f"  Overall: {verdict.overall:.1f}/5  |  {verdict.reasoning}")

        assert verdict.overall >= 3.5, (
            f"Single-article summary quality: {verdict.overall:.1f} < 3.5\n"
            f"Reasoning: {verdict.reasoning}"
        )

        # ── Programmatic content checks ──
        answer_lower = answer.lower()

        # Must reference the source page (by slug, title, or URL)
        assert any(marker in answer_lower for marker in [
            "uncomfortable-truths",    # filename slug
            "uncomfortable truths",    # natural title
            "standupforme",            # domain
        ]), (
            "Answer doesn't reference the uncomfortable-truths article by name, title, or URL"
        )

        # Must mention at least 2 of the article's key critiques
        critique_markers = [
            "scaffolding",        # the scaffolding problem
            "institutional",      # institutional context gap
            "production",         # production-readiness
            "silent",             # silent failures / silent optimization erosion
            "rewrite",            # 30-40% rewrite rate
            "architectural",      # architectural drift / incoherence
            "ip", "copyright",    # IP/copyright overhang
            "performance",        # silent performance regressions
        ]
        critiques_found = [m for m in critique_markers if m in answer_lower]
        assert len(critiques_found) >= 2, (
            f"Expected ≥2 critique markers, got {len(critiques_found)}: {critiques_found}. "
            "The summary may be too shallow or pulling from the wrong page."
        )
        print(f"  Critique markers found: {critiques_found}")
