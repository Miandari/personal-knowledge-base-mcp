---
type: entity
title: "claude-obsidian"
aliases:
  - "AgriciDaniel/claude-obsidian"
created: 2026-04-11
updated: 2026-04-11
tags:
  - llm-wiki-pattern
  - claude-code-skill
  - github-repository
  - agent-memory
status: mature
entity_type: repository
role: "Claude + Obsidian wiki vault — the base this vault is built on"
first_mentioned: "[[.raw/notion/2026-04-10.md]]"
related:
  - "[[llm-wiki-pattern]]"
  - "[[claude-code]]"
  - "[[agent-memory]]"
sources:
  - "[[.raw/notion/2026-04-10.md]]"
---

# claude-obsidian

**GitHub**: https://github.com/AgriciDaniel/claude-obsidian
**Language**: Shell
**License**: MIT
**Observed**: 352★ (as of 2026-04-10), currently 490★+

Claude + Obsidian personal knowledge companion. Explicit implementation of the [[llm-wiki-pattern|Karpathy LLM wiki pattern]] using Obsidian as the markdown substrate.

**This vault's base.** Installed and customized on 2026-04-11. The canonical reason it was chosen over `eugeniughelbur/obsidian-second-brain` despite the task description naming the latter: claude-obsidian is a full Claude Code plugin with 10 skills (wiki, wiki-ingest, wiki-query, wiki-lint, save, autoresearch, canvas, defuddle, obsidian-bases, obsidian-markdown), working hooks.json, frontmatter schema reference, and vault templates — while obsidian-second-brain ships 25 slash commands with no hooks, schema, or templates.

## Skills shipped

- `wiki` — scaffold, route to sub-skills
- `wiki-ingest` — source ingestion (URL, image, batch, delta-tracked, contradiction-aware)
- `wiki-query` — three-mode retrieval (quick/standard/deep) with hot cache priority
- `wiki-lint` — orphan/gap detection
- `save` — file conversation as wiki note
- `autoresearch` — autonomous search → fetch → synthesize → file
- `canvas` — Obsidian canvas integration
- `defuddle` — strip ads/nav from fetched URLs
- `obsidian-bases`, `obsidian-markdown` — Obsidian syntax references

## Hooks shipped

Real, working `hooks/hooks.json` with SessionStart (cat `wiki/hot.md`), PostCompact (re-read), PostToolUse (**auto git-commit after every Write/Edit**), and Stop (prompt injection telling Claude to update hot.md at end-of-response). The **Stop prompt hook** solves the "how do you update hot.md when Stop hooks can only run shell commands" problem elegantly — you inject a prompt telling Claude to do it as part of its own response.

## Documented issue

- `anthropics/claude-code#10875` — plugin hook STDOUT may not be captured by Claude Code. Workaround: install hooks in vault-local or user-level `settings.json` rather than distributing as a plugin. This vault follows that workaround.

## Related

- [[llm-wiki-pattern]]
- [[agent-memory]]
- [[claude-code]]
- NicholasSpisak/second-brain — the independent parallel implementation of the same pattern, observed in the same 2026-04-10 briefing
