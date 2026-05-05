---
title: LLM Wiki pattern
origin: note
status: developing
aliases:
  - "Karpathy LLM wiki"
  - "compiled knowledge base"
  - "persistent agent memory wiki"
  - "compilation over retrieval"
  - "concepts/llm-wiki-pattern"
tags:
  - llm-wiki-pattern
  - agent-memory
  - knowledge-management
  - compilation-over-retrieval
related:
  - "[[agent-memory]]"
  - "[[claude-obsidian]]"
  - "[[mempalace]]"
  - "[[ai-coding-agents]]"
sources: []
raw_sources:
  - ".raw/notion/2026-03-28.md"
  - ".raw/notion/2026-04-10.md"
  - ".raw/notion/2026-04-11.md"
complexity: intermediate
domain: ai-development
created_at: 2026-04-11
updated_at: 2026-04-11
---

# LLM Wiki pattern

The **LLM Wiki pattern** — originally articulated by Andrej Karpathy — is the idea that an agent should maintain a **persistent, compounding, human-readable knowledge base** of a project (or a life, or a codebase, or a domain) rather than re-deriving context from raw sources each session.

The pattern's central claim: **compilation beats retrieval**. A pre-written wiki page that the agent itself authored and keeps up to date is cheaper (fewer tokens), more accurate (already synthesized), and more compounding (gets smarter over time) than redoing RAG or rereading documentation from scratch every time a question comes in.

This vault is an instance of the pattern.

## Why this matters now

Across three of the four briefings ingested (2026-03-28, 2026-04-10, 2026-04-11), the pattern has gone from "Karpathy tweet" to "genuine wave of independent implementations." The 2026-04-10 Signal line put it bluntly: *"five independent repos converging on 'agent maintains a compact structured knowledge base of your project / life so it doesn't re-learn from scratch each session.' Durable, declarative, human-readable artifacts (skills, wikis, memories) are beating ephemeral context windows."*

The 2026-04-11 briefing reinforced this: **memory infrastructure is now the dominant agent-tooling theme** (Signal line). mempalace alone was 5,871 stars/day on 2026-04-11.

## Implementations observed in briefings

| Project | What it is | Observed in | Stars |
|---|---|---|---|
| [[mempalace]] (milla-jovovich/mempalace) | ChromaDB-based memory system with a "highest-scoring AI memory system ever benchmarked" claim | 4/10, 4/11 | ~41k |
| [[claude-obsidian]] (AgriciDaniel/claude-obsidian) | Claude + Obsidian personal knowledge companion, explicit LLM-wiki implementation. **This vault's base.** | 4/10 | 352+ |
| NicholasSpisak/second-brain | LLM-maintained Obsidian vault, same pattern, independent build | 4/10 | 86 |
| nashsu/llm_wiki | Cross-platform desktop app that turns arbitrary documents into an agent-queryable wiki. Direct implementation of Karpathy's proposal. | 4/11 | — |
| sdyckjq-lab/llm-wiki-skill | Shell-packaged Claude skill implementing the LLM-wiki pattern | 4/11 | — |
| Houseofmvps/codesight | Project-context bundle generator for Claude Code / Cursor / Copilot | 4/10 | 782 |
| coleam00/claude-memory-compiler | Compiles codebase-interaction history into Claude Code memory layer | 4/11 | — |
| Memoriki | LLM Wiki + MemPalace hybrid for persistent personal KBs (Show HN) | 4/10 | — |
| PrathamLearnsToCode/paper2code | Agent skill that turns an arXiv paper into working code — narrow but illustrative | 4/11 | — |
| Memento-Skills (VentureBeat) | Research framework where agents rewrite their own skills without retraining — treats skills as mutable external memory | 4/11 | — |

The fact that two independent Obsidian-flavored implementations (claude-obsidian and NicholasSpisak/second-brain) were both trending in the same week is the signal the 2026-04-10 briefing specifically flagged.

## The core insight (why it works)

Ephemeral context (everything the agent sees in a single session, then throws away) is **expensive, forgetful, and redundant**. You pay per-token to rederive the same understanding, the agent gets no smarter between sessions, and most of the context window is filler.

The LLM Wiki pattern flips this: **every answer also updates the wiki**. What you learn in a session becomes durable — the next session starts from the compiled state, not the raw sources. This is a two-output rule: the user gets an answer, and the wiki gets a new / updated page.

Concrete consequences:

1. **Compilation beats retrieval.** Reading `wiki/concepts/agent-memory.md` is cheaper than semantic-searching 50 raw sources and re-synthesizing them on the fly.
2. **The wiki gets smarter, not bigger.** When a new source arrives, existing pages get **rewritten** to integrate it. A dumping ground grows linearly; a second brain grows sub-linearly in size but super-linearly in quality.
3. **Human-readable artifacts compound across sessions and across collaborators.** A wiki is readable by the next human AND the next LLM. A vector DB is readable by neither.
4. **Agents that research before they edit outperform agents that don't.** The "Research-Driven Agents" HN pattern (193pts, [[.raw/notion/2026-04-10.md|4/10 briefing]]) argues that forcing an explicit research phase (read docs, read existing code, summarize) before editing materially improves outcomes. A pre-compiled wiki is exactly the artifact that research phase should read first.

## Related architectural patterns

- [[agent-memory]] — the broader memory infrastructure wave (of which LLM-wiki is a specific flavor)
- **Skills as mutable external memory** (Memento-Skills, obra/superpowers) — a parallel instance of the same principle: externalize the agent's capability into composable, rewriteable `SKILL.md` files
- **Advisor / executor split** — the planner consults a wiki, the executors don't need to
- **Hot cache** — the very smallest-scale version of the same principle: a ~500-token summary of recent context that loads on every session start (this vault does this via `wiki/hot.md`)

## Compared to RAG / vector-only search

RAG retrieves. The LLM Wiki compiles. The difference matters:

| Dimension | Pure RAG | LLM Wiki |
|---|---|---|
| Unit of knowledge | Raw document chunks | Synthesized, rewritten pages |
| Grows with use | No (same corpus) | Yes (pages get rewritten) |
| Context cost | High (re-synthesize every query) | Low (already synthesized) |
| Human-inspectable | Indirectly | Directly (it's literally a wiki) |
| Handles contradictions | Silent conflicting chunks | Explicit contradiction callouts, bi-temporal facts |
| Best for | Static document corpora | Evolving personal or project knowledge |

Hybrid approaches (like this vault) combine the two: the LLM Wiki is the knowledge representation, [[qmd]] provides the hybrid BM25 + vector + rerank search layer on top. You still get semantic search, but it searches **compiled pages**, not raw dumps.

## Key queries this concept should answer

- "what is the LLM wiki pattern"
- "why compile instead of retrieve"
- "who is building agent-owned knowledge bases" → see the implementation table
- "what did Karpathy say about wikis"
- "how to make an agent smarter over time" → the two-output rule + compilation over retrieval
- "what is the relationship between skills and wikis" → both are externalized, mutable, human-readable agent state
