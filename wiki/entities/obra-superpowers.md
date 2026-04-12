---
type: entity
title: "obra/superpowers"
aliases:
  - "superpowers"
  - "Jesse Vincent's superpowers"
created: 2026-04-11
updated: 2026-04-11
tags:
  - ai-coding-agents
  - claude-code
  - github-repository
  - skills-framework
status: developing
entity_type: repository
role: "Composable SKILL.md-based agent skills framework and software development methodology"
first_mentioned: "[[.raw/notion/2026-03-28.md]]"
related:
  - "[[claude-code]]"
  - "[[ai-coding-agents]]"
  - "[[llm-wiki-pattern]]"
sources:
  - "[[.raw/notion/2026-03-28.md]]"
---

# obra/superpowers

**GitHub**: https://github.com/obra/superpowers
**Language**: Shell
**Author**: Jesse Vincent (Prime Radiant)

Composable `SKILL.md`-based agent skills framework and opinionated software development methodology. Workflows: the agent specs the work with you, builds an implementation plan, then executes with TDD.

**Interop**: Works with Claude Code, Cursor, Codex, OpenCode. Available via the Claude plugin marketplace.

## Observed growth

- **March 28, 2026** — **#1 trending on GitHub that day**, 2,293 stars/day, 120k total stars. The top trending repo on March 28 by a wide margin.
- Sustained traction throughout the Q2 2026 [[agent-memory]] / skills-framework wave

## Why it matters

obra/superpowers is the de-facto reference for the **skills-framework** architectural pattern as of Q2 2026. It instantiates the exact "skills as mutable external memory" idea that Memento-Skills (AAAI 2026) formalized from the research side. The skills are composable `SKILL.md` files, which means:

1. They're human-readable (same property as [[llm-wiki-pattern|LLM Wiki pages]])
2. They can be edited by the agent without retraining
3. They compose into workflows (research → plan → TDD → execute)
4. They are portable across agent harnesses

This puts superpowers in the same conceptual family as [[claude-obsidian]] and [[mempalace]] even though the axis is different: superpowers externalizes **how the agent acts**, claude-obsidian externalizes **what the agent knows**, mempalace externalizes **what the agent remembers**. All three are instances of the same macro-pattern: agents owe their durability to external, editable artifacts, not to ephemeral context.

## Related

- [[claude-code]] — the primary client
- [[ai-coding-agents]]
- [[llm-wiki-pattern]]
