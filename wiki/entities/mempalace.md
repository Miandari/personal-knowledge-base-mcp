---
type: entity
title: "mempalace"
aliases:
  - "milla-jovovich/mempalace"
created: 2026-04-11
updated: 2026-04-11
tags:
  - agent-memory
  - github-repository
  - chromadb
status: developing
entity_type: repository
role: "ChromaDB-based memory system for agents, marketed as the highest-scoring AI memory system on current benchmarks"
first_mentioned: "[[.raw/notion/2026-04-10.md]]"
related:
  - "[[agent-memory]]"
  - "[[llm-wiki-pattern]]"
sources:
  - "[[.raw/notion/2026-04-10.md]]"
  - "[[.raw/notion/2026-04-11.md]]"
---

# mempalace

**GitHub**: https://github.com/milla-jovovich/mempalace
**Language**: Python
**License**: MIT (per 4/11 briefing)

ChromaDB-based memory system for AI agents, positioning itself as "the highest-scoring AI memory system ever benchmarked." One of the anchor repos of the Q2 2026 [[agent-memory]] wave.

## Observed growth

| Date | Stars/day | Total stars | Notes |
|---|---|---|---|
| 2026-04-10 | — | ~39k | First appearance in the briefings |
| 2026-04-11 | **5,871** | ~41k | Highest stars/day across the GitHub trending section that day — the viral moment |

The ~2k stars gained in a single day (at the 5,871/day rate) is typical of "benchmark-claim-goes-viral" trajectories. The 2026-04-11 Signal line called it out explicitly: *"mempalace (5,871★/day), claude-memory-compiler, llm_wiki, llm-wiki-skill, and Memento-Skills all hit trending or research feeds in the same 48-hour window. The market is consolidating around 'external, mutable, agent-owned knowledge' rather than longer context windows."*

## Positioning

The headline claim — "highest-scoring AI memory system ever benchmarked" — is doing most of the virality work. As noted under [[agent-memory#Open questions]], the benchmark methodology is unresolved: **on whose benchmark?** This is the biggest unanswered methodology question in the entire memory-infrastructure wave.

That caveat aside, the library is a ChromaDB (vector DB) wrapper with an agent-facing API, and it sits in the same conceptual cluster as:

- [[claude-obsidian]] — LLM-wiki style, markdown substrate
- NicholasSpisak/second-brain — LLM-wiki style, Obsidian substrate
- Memoriki — hybrid LLM-wiki + MemPalace design
- coleam00/claude-memory-compiler — Claude Code-scoped memory compiler

Where mempalace differs: pure vector DB, not a human-readable artifact. Trade-off is the usual one — scale + similarity search vs. legibility and compoundability.

## Related

- [[agent-memory]]
- [[llm-wiki-pattern]]
- [[ai-coding-agents]]
