---
type: concept
title: "Agent memory"
aliases:
  - "LLM memory"
  - "persistent agent memory"
  - "external agent memory"
created: 2026-04-11
updated: 2026-04-11
tags:
  - agent-memory
  - llm-wiki-pattern
  - knowledge-management
  - infrastructure
status: developing
complexity: intermediate
domain: ai-development
related:
  - "[[llm-wiki-pattern]]"
  - "[[llm-context-scaling]]"
  - "[[ai-coding-agents]]"
  - "[[mempalace]]"
sources:
  - "[[.raw/notion/2026-03-27.md]]"
  - "[[.raw/notion/2026-04-10.md]]"
  - "[[.raw/notion/2026-04-11.md]]"
---

# Agent memory

**Agent memory** infrastructure is the fastest-growing category in agent tooling as of Q2 2026. The central claim of the wave: **the market is consolidating around "external, mutable, agent-owned knowledge" rather than longer context windows** ([[.raw/notion/2026-04-11.md|4/11 Signal]]).

## The thesis

Context windows are a **rental** — you pay per token, per session, to rederive the same state. Agent memory is **ownership** — a compact, persistent, durable knowledge artifact that the agent writes, reads, and updates across sessions without re-paying each time.

The shift is architectural, not incremental: the field is moving from "stuff everything into the context window" to "maintain a compact, rewriteable memory store that the agent queries against." The 2026-04-11 briefing's Signal line made this explicit — memory infrastructure is now the dominant agent-tooling theme, not a sidecar.

Karpathy's viral memory thread (referenced in the 2026-03-27 briefing as the catalyst for MemMA and similar work) argued that **LLM memory is architecturally limited** — that no amount of scaling the context window will fix the compounding problem, and that external, structured, mutable memory is the real answer.

## Key projects observed in briefings

### Memory stores (infrastructure)

| Project | What it is | Observed | Size |
|---|---|---|---|
| [[mempalace]] (milla-jovovich) | ChromaDB-based memory; "highest-scoring AI memory system on current benchmark suite" | 4/10, 4/11 | ~41k⭐, 5,871⭐/day on 4/11 |
| coleam00/claude-memory-compiler | Compiles Claude Code codebase-interaction history into evolving memory | 4/11 | Python |
| Superfast | Cognitive memory graphs for enterprise AI agents (Show HN) | 3/27 | — |
| MemMA (research paper) | Coordinating the memory cycle through multi-agent reasoning and in-situ self-evolution | 3/27 | HuggingFace paper |
| Memento-Skills (VentureBeat) | Treats skills as mutable external memory — agents rewrite their own skills without retraining | 4/11 | Framework |

### LLM-wiki implementations (the specific flavor of agent memory where the store is a human-readable wiki)

| Project | Observed | Notes |
|---|---|---|
| [[claude-obsidian]] | 4/10 | This vault's base |
| NicholasSpisak/second-brain | 4/10 | Independent Obsidian-flavored build |
| nashsu/llm_wiki | 4/11 | Cross-platform desktop app |
| sdyckjq-lab/llm-wiki-skill | 4/11 | Shell-packaged Claude skill |
| Memoriki (Show HN) | 4/10 | LLM Wiki + MemPalace hybrid |

See [[llm-wiki-pattern]] for the full narrative on that sub-thread.

### Context bundles / scaffolding (memory-adjacent tooling)

| Project | What it does | Observed |
|---|---|---|
| Houseofmvps/codesight | Universal project-context generator that produces a single compact bundle for Claude Code / Cursor / Copilot | 4/10 |
| JuliusBrussee/caveman | Token-compression skill: rewrites prompts in terse caveman English for ~65% output token reduction | 4/10, 4/11 |

These are not memory per se — they are the **context-efficiency** half of the same story. If the memory store lives outside the context window, you still need to shove *something* into the window on each request, and you want that something to be maximally compressed.

## Architectural patterns

1. **External mutable store + pointer-based lookup.** The agent holds a tiny pointer in context (a page name, a URL, a docid) and fetches the full content only when needed. [[mempalace]] and [[claude-obsidian]] both do this, though the storage substrate differs (ChromaDB vs markdown files).

2. **Compilation over retrieval.** See [[llm-wiki-pattern]]. Pages are **rewritten** when new information arrives, not just appended — so the memory compounds in quality, not just volume.

3. **Skills as mutable external memory.** Memento-Skills and obra/superpowers treat the agent's *capabilities* themselves as an external, editable knowledge store. Same principle, different axis: instead of "what does the agent know about X" you externalize "how does the agent do X."

4. **Hot caches and session-bridging state.** The smallest-scale version of the same principle. A ~500-token summary loaded at session start bridges what was learned last session into the current one. This vault does this via `wiki/hot.md` + a SessionStart hook.

5. **Research-driven agents.** The agent reads its memory **before** it acts on a user request. The HN "Research-Driven Agents" pattern writeup (193pts, [[.raw/notion/2026-04-10.md|4/10]]) is the canonical articulation.

## Why this is a wave and not a fad

Three independent signals:

1. **Volume and velocity.** mempalace at 5,871 stars/day (2026-04-11) is not a niche project — it is a mass-market concern.
2. **Convergence.** Five (at least) independent implementations of the LLM-wiki pattern appeared within a two-week window, built by people who almost certainly didn't coordinate.
3. **Research follows.** Memento-Skills (AAAI-adjacent), MemMA (HF papers), and the Autonomous Multi-Agent Evolution Framework from MIT all treat persistent memory as a first-class architectural concern rather than an implementation detail.

## Open questions the briefings don't answer

- **Benchmark design.** mempalace claims "highest-scoring ever benchmarked" — on what benchmark? Is there a shared benchmark or is everyone scoring against their own setup? This is the biggest unresolved methodology question in the wave.
- **Storage-substrate tradeoffs.** ChromaDB (mempalace) vs SQLite (qmd) vs flat markdown (Obsidian vaults) vs graph DB (Supermemory's temporal knowledge graphs) — the field hasn't settled on a default.
- **Contamination.** If the memory is agent-owned and agent-rewritten, how do you prevent the agent from laundering hallucinations into persistent state? The contradiction-callout pattern (`> [!contradiction]`) is a partial answer but not a full one.

## Related

- [[llm-wiki-pattern]] — the specific "wiki as agent memory" sub-pattern this vault instantiates
- [[llm-context-scaling]] — the competing strategy (bigger context window). MSA (100M tokens) and TurboQuant make context cheaper, which partially undermines the memory wave's thesis — or complements it, depending on your view
- [[ai-coding-agents]] — the primary consumers of agent-memory infrastructure
- [[mcp-ecosystem]] — the protocol layer through which memory-as-a-service is delivered to agents
