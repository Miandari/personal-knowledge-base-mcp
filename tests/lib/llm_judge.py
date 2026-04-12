"""LLM-as-judge for evaluating KB synthesis quality.

Supports four providers: anthropic, openai, google, openrouter.
Configure via environment variables (see .env.example).
"""

import json
import os
from dataclasses import dataclass


@dataclass
class JudgeVerdict:
    groundedness: int  # 1-5: is the answer grounded in the provided wiki pages?
    citation_correctness: int  # 1-5: do the [[wikilinks]] point to real, relevant pages?
    hallucination: int  # 1-5: 5 = no hallucination, 1 = heavily fabricated
    relevance: int  # 1-5: does the answer actually address the question?
    overall: float  # mean of the four scores
    reasoning: str  # the judge's free-text reasoning

    @classmethod
    def from_scores(cls, groundedness, citation, hallucination, relevance, reasoning):
        return cls(
            groundedness=groundedness,
            citation_correctness=citation,
            hallucination=hallucination,
            relevance=relevance,
            overall=(groundedness + citation + hallucination + relevance) / 4,
            reasoning=reasoning,
        )


JUDGE_SYSTEM_PROMPT = """\
You are a strict evaluator of knowledge-base synthesis answers. You will be given:
1. A user question
2. The wiki pages that were retrieved (the source material)
3. A synthesized answer produced from those pages

Score the answer on four dimensions (1 = terrible, 5 = excellent):

- **Groundedness**: Is every claim in the answer supported by the provided wiki pages? Deduct for claims that go beyond the source material.
- **Citation correctness**: Do the [[wikilinks]] in the answer point to real pages that actually support the claims they're attached to? Deduct for missing citations or citations that don't match.
- **Hallucination**: Is the answer free of fabricated facts? 5 = nothing fabricated. 1 = heavily fabricated.
- **Relevance**: Does the answer actually address the question asked?

Respond with ONLY valid JSON in this exact format (no markdown, no explanation outside the JSON):
{"groundedness": <1-5>, "citation_correctness": <1-5>, "hallucination": <1-5>, "relevance": <1-5>, "reasoning": "<2-3 sentence explanation>"}
"""


def _build_judge_prompt(question: str, wiki_pages: str, answer: str) -> str:
    return (
        f"## Question\n{question}\n\n"
        f"## Retrieved wiki pages\n{wiki_pages}\n\n"
        f"## Synthesized answer\n{answer}\n\n"
        f"Score this answer."
    )


def judge_with_anthropic(question: str, wiki_pages: str, answer: str, model: str = "") -> JudgeVerdict:
    import anthropic

    model = model or os.getenv("TEST_JUDGE_MODEL") or "claude-sonnet-4-20250514"
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=model,
        max_tokens=500,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_judge_prompt(question, wiki_pages, answer)}],
    )
    return _parse_verdict(response.content[0].text)


def judge_with_openai(question: str, wiki_pages: str, answer: str, model: str = "") -> JudgeVerdict:
    from openai import OpenAI

    model = model or os.getenv("TEST_JUDGE_MODEL") or "gpt-4.1"
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        max_tokens=500,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_judge_prompt(question, wiki_pages, answer)},
        ],
    )
    return _parse_verdict(response.choices[0].message.content)


def judge_with_google(question: str, wiki_pages: str, answer: str, model: str = "") -> JudgeVerdict:
    from google import genai

    model = model or os.getenv("TEST_JUDGE_MODEL") or "gemini-2.5-pro"
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=model,
        contents=f"{JUDGE_SYSTEM_PROMPT}\n\n{_build_judge_prompt(question, wiki_pages, answer)}",
    )
    return _parse_verdict(response.text)


def judge_with_openrouter(question: str, wiki_pages: str, answer: str, model: str = "") -> JudgeVerdict:
    from openai import OpenAI

    model = model or os.getenv("TEST_JUDGE_MODEL") or "anthropic/claude-sonnet-4"
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=500,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_judge_prompt(question, wiki_pages, answer)},
        ],
    )
    return _parse_verdict(response.choices[0].message.content)


def get_judge():
    """Return the judge function matching TEST_JUDGE_PROVIDER env var."""
    provider = os.getenv("TEST_JUDGE_PROVIDER", "anthropic")
    judges = {
        "anthropic": judge_with_anthropic,
        "openai": judge_with_openai,
        "google": judge_with_google,
        "openrouter": judge_with_openrouter,
    }
    if provider not in judges:
        raise ValueError(f"Unknown judge provider: {provider}. Choose from: {list(judges.keys())}")
    return judges[provider]


def _parse_verdict(raw: str) -> JudgeVerdict:
    """Parse the JSON response from the judge LLM."""
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)
    return JudgeVerdict.from_scores(
        groundedness=int(data["groundedness"]),
        citation=int(data["citation_correctness"]),
        hallucination=int(data["hallucination"]),
        relevance=int(data["relevance"]),
        reasoning=data.get("reasoning", ""),
    )
