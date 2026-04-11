---
type: concept
title: "AI coding agents"
aliases:
  - "agentic coding"
  - "AI coding assistants"
  - "coding agents"
created: 2026-04-11
updated: 2026-04-11
tags:
  - ai-coding-agents
  - software-engineering
  - critique
  - production-readiness
status: developing
complexity: intermediate
domain: ai-development
related:
  - "[[claude-code]]"
  - "[[uncomfortable-truths-ai-coding-agents]]"
  - "[[llm-wiki-pattern]]"
  - "[[agent-memory]]"
sources:
  - "[[uncomfortable-truths-ai-coding-agents]]"
  - "[[.raw/notion/2026-03-27.md]]"
  - "[[.raw/notion/2026-03-28.md]]"
  - "[[.raw/notion/2026-04-10.md]]"
  - "[[.raw/notion/2026-04-11.md]]"
---

# AI coding agents

**AI coding agents** are LLM-driven tools that edit code autonomously — Claude Code, Cursor, Devin, GitHub Copilot workspace, Windsurf, the OpenClaw/Hermes harness family, and the obra/superpowers skill framework. They differ from plain autocomplete in that they can execute multi-step plans (read files → write patches → run tests → iterate) inside a working repository with minimal human intervention between steps.

This is the canonical vault concept for tracking the ongoing, multi-faceted conversation around them: **capabilities, production limits, critical takes, adjacent tooling, and the emerging "agent harness" architectural pattern**.

## Current state (as of 2026-04-11)

### Capabilities are real but jagged

Agents are credibly doing useful work for scaffolding, boilerplate, and well-defined edits. ATLAS on a $500 GPU hits 74.6% on 599 LiveCodeBench tasks at 1/16 the cost of Claude Sonnet ([[.raw/notion/2026-03-27.md|3/27 briefing]]). Anthropic's [[advisor-strategy|Advisor Strategy]] pattern — Opus as planner, Sonnet/Haiku as executor — gains +2.7pp on SWE-bench Multilingual at 11.9% lower per-task cost ([[.raw/notion/2026-04-11.md|4/11 briefing]]).

But the **jagged-intelligence** framing (Ethan Mollick, [[.raw/notion/2026-04-10.md|4/10 briefing]]) captures why capability claims keep disappointing people in practice:

- Weaknesses are not intuitive or identifiable in advance.
- All frontier LLMs share similar weaknesses, so "just hire a different one" is not a mitigation.
- The frontier is moving outward, so your mental model is always stale.

### Production readiness is the live fault line

[[uncomfortable-truths-ai-coding-agents|Sarah's "uncomfortable truths" post]] is the clearest **critical** articulation of the production-readiness gap: agents can write individual functions but not reason about institutional context (why a mock exists, why a variable is overridden in staging, why a function that looks redundant is a linchpin). The resulting failure mode is silent — code compiles, tests pass, performance quietly degrades, architectural intent erodes. Practitioners report rewriting 30-40% of generated code when the domain is non-trivial.

The SlopCodeBench paper ([[.raw/notion/2026-03-27.md|3/27 briefing]]) is trying to **quantify** this same phenomenon — how agent code quality degrades over long-horizon iterative tasks. The fact that a benchmark for "slop" now exists is itself a signal that the community has moved past "can agents code at all" into "when and why do they stop working well."

### The emerging architectural pattern: advisor + harness + skills

Three threads are converging:

1. **Advisor / executor split** — one expensive planner, many cheap workers. Anthropic shipped this as a Messages API pattern ([[.raw/notion/2026-04-11.md|4/11 briefing]]). The economics and the capability bump are real.
2. **Harnesses** — OpenClaw, Hermes, HKUDS/OpenHarness, Gitlawb/openclaw. A single CLI that speaks to 200+ models through one surface, so the planner is model-agnostic and the executor pool can be tuned by cost/quality.
3. **Skills as mutable external memory** — [[obra-superpowers|obra/superpowers]] (120k⭐, #1 trending 2026-03-28), Memento-Skills (AAAI 2026), [[claude-obsidian]]. The agent owns a growing library of composable `SKILL.md` files that describe **how** to do things, edited by the agent itself without retraining.

The pattern name practitioners have settled on is "**one smart planner + many cheap executors + growing skill library**." The prototype phase ("can we make a Python script that calls an LLM in a loop?") is ending; the platform phase — JetBrains Central, Dapr Agents v1.0, Microsoft Agent Framework — is beginning.

### Research-driven agents

A notable HN pattern writeup (193pts, [[.raw/notion/2026-04-10.md|4/10 briefing]]) argues that forcing the agent through an explicit **research phase** (read docs → read existing code → summarize) before editing materially improves outcomes. Karpathy's [[.raw/notion/2026-04-10.md|autoresearch experiment]] is the canonical instance of this pattern — the r/MachineLearning controlled experiment showing 3.2% improvement from giving agents access to literature is a direct consequence of it.

This dovetails with the [[llm-wiki-pattern]]: agents that read a pre-compiled project wiki before editing outperform agents that re-derive context from the code each session.

## Known limits (red-team list)

Drawn primarily from [[uncomfortable-truths-ai-coding-agents]], the SlopCodeBench motivation ([[.raw/notion/2026-03-27.md]]), Mollick's jagged-intelligence framing ([[.raw/notion/2026-04-10.md]]), and the ongoing Claude Code `/Windows` pain threads:

| Failure mode | What happens | Why it matters |
|---|---|---|
| Institutional context gap | Can refactor working code into something that compiles but breaks intent | Failures are silent — no test catches them |
| Net productivity inversion | Debugging + rewriting > writing from scratch on domain-specific code | The "10× programmer" claim is false on non-trivial work |
| Silent optimization erosion | Undoes careful perf optimizations because they "look redundant" | p99 regressions ship unnoticed |
| Architectural drift | Can't hold the cross-cutting discipline of a senior reviewer | Codebases degrade incrementally under repeated agent edits |
| Token inflation | Responses have gotten longer, reducing exchanges per session ([[.raw/notion/2026-03-27.md\|Claude rate limit thread]]) | Users pay more for the same work |
| IP / copyright overhang | Whole-codebase AI generation puts the IP status of the code in limbo | Legal time bomb, not a technical issue |

## Where they do work

- **Non-coders bringing ideas to life** — prototyping, proof-of-concept. The goal is exploration, not production. ([[uncomfortable-truths-ai-coding-agents]])
- **Experienced coders on recreational side projects** — as long as there is no business at the end of the project.
- **Scaffolding + boilerplate** — the original Copilot use case. Still the most reliable zone.
- **Explicit-plan-first workflows** — "research-driven agents" pattern, advisor/executor split with TDD, skills-based decomposition (obra/superpowers).

## Related concepts

- [[uncomfortable-truths-ai-coding-agents]] — the canonical critical / red-team source
- [[llm-wiki-pattern]] — compilation over retrieval, compounding knowledge, research-driven agents
- [[agent-memory]] — mempalace, MemMA, Memento-Skills, the memory-infrastructure wave
- [[mcp-ecosystem]] — the protocol layer agents use to talk to tools
- [[llm-context-scaling]] — MSA, TurboQuant, KV-cache compression — why context length limits are receding
- [[claude-code]] — the primary agent the user interacts with daily

## Key queries this concept should answer

- "critical takes on AI coding agents" → [[uncomfortable-truths-ai-coding-agents]]
- "where does Claude Code fall short in production" → this page + [[uncomfortable-truths-ai-coding-agents]]
- "honest problems with current AI coding tools" → this page
- "what is the state of agentic coding in Q2 2026" → this page
- "should I use AI agents for production code" → no, per [[uncomfortable-truths-ai-coding-agents]], unless you accept the silent failure modes listed above
