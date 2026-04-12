"""Synthesis quality tests via LLM-as-judge.

For a set of queries:
1. Retrieve relevant wiki pages via kb search
2. Construct a synthesis prompt
3. Call Claude (or the configured LLM) to produce an answer
4. Call the LLM judge to rate the answer

Requires ANTHROPIC_API_KEY (or the configured judge's API key) in .env.
"""

import os
from pathlib import Path

import pytest

import sys
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tests.lib.llm_judge import get_judge, JudgeVerdict
from tests.lib.kb_client import kb_query, kb_get

# Skip the entire module if no API key is available
pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set -- skipping LLM judge tests",
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


def _synthesize_answer(query: str) -> tuple[str, str]:
    """Retrieve pages and produce a synthesis. Returns (wiki_pages_text, answer)."""
    import anthropic

    # Retrieve via kb_client
    results = kb_query(query, n=5, mode="hybrid_no_rerank")
    if not results:
        return ("(no results)", "(no answer -- search returned nothing)")

    # Fetch full pages
    pages_text = ""
    for r in results[:3]:
        try:
            content = kb_get(r.node_id)
            pages_text += f"\n\n--- {r.title} ({r.path}) ---\n{content[:3000]}"
        except (RuntimeError, Exception):
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
    """Test that cross-briefing synthesis actually works."""

    @pytest.mark.timeout(120)
    def test_cross_briefing_overview(self, judge_fn):
        query = (
            "Summarize what I've learned about AI agent infrastructure "
            "in the last two weeks"
        )
        wiki_pages, answer = _synthesize_answer(query)

        verdict = judge_fn(question=query, wiki_pages=wiki_pages, answer=answer)
        print(f"\n--- Multi-source synthesis ---")
        print(f"  Overall: {verdict.overall:.1f}/5  |  {verdict.reasoning}")

        assert verdict.overall >= 3.0, (
            f"Multi-source synthesis quality: {verdict.overall:.1f} < 3.0\n"
            f"Reasoning: {verdict.reasoning}"
        )

        import re
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", answer)
        unique_links = set(wikilinks)

        assert len(unique_links) >= 3, (
            f"Expected >=3 unique [[wikilinks]], got {len(unique_links)}: {unique_links}. "
        )

        tool_keywords = [
            "mempalace", "superpowers", "claude-obsidian", "codesight",
            "caveman", "openclaude", "memoriki", "qmd", "dapr",
            "jetbrains central", "agentguard", "agentmint", "crewai",
            "openharness", "memento-skills", "atlas", "second-brain",
            "memento", "mcp", "obra",
        ]
        mentioned = [kw for kw in tool_keywords if kw.lower() in answer.lower()]
        assert len(mentioned) >= 2, (
            f"Expected >=2 tools/repos mentioned, got {len(mentioned)}: {mentioned}. "
        )

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
            f"Expected >=2 sub-topics covered, got {len(topics_covered)}: {topics_covered}. "
        )
        print(f"  Breadth: {len(unique_links)} wikilinks, {len(mentioned)} tools, {len(topics_covered)} sub-topics")


class TestSingleArticleSummary:
    """Test that the system can summarize a specific known article."""

    @pytest.mark.timeout(120)
    def test_summarize_uncomfortable_truths(self, judge_fn):
        query = (
            "Summarize the article 'Some uncomfortable truths about AI coding agents' "
            "from standupforme.app"
        )
        wiki_pages, answer = _synthesize_answer(query)

        verdict = judge_fn(question=query, wiki_pages=wiki_pages, answer=answer)
        print(f"\n--- Single-article summary ---")
        print(f"  Overall: {verdict.overall:.1f}/5  |  {verdict.reasoning}")

        assert verdict.overall >= 3.5, (
            f"Single-article summary quality: {verdict.overall:.1f} < 3.5\n"
            f"Reasoning: {verdict.reasoning}"
        )

        answer_lower = answer.lower()
        assert any(marker in answer_lower for marker in [
            "uncomfortable-truths", "uncomfortable truths", "standupforme",
        ]), "Answer doesn't reference the uncomfortable-truths article"

        critique_markers = [
            "scaffolding", "institutional", "production", "silent",
            "rewrite", "architectural", "ip", "copyright", "performance",
        ]
        critiques_found = [m for m in critique_markers if m in answer_lower]
        assert len(critiques_found) >= 2, (
            f"Expected >=2 critique markers, got {len(critiques_found)}: {critiques_found}. "
        )
        print(f"  Critique markers found: {critiques_found}")
