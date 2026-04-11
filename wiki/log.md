---
type: meta
title: "Operation log"
created: 2026-04-11
updated: 2026-04-11
status: developing
---

# Log

Append-only operation log. Newest entries at the TOP.

## [2026-04-11] kickoff ingest | 4 briefings compiled

- **Briefings ingested**: 2026-03-27, 2026-03-28, 2026-04-10, 2026-04-11
- **Raw dumps**: `.raw/notion/2026-03-27.md`, `.raw/notion/2026-03-28.md`, `.raw/notion/2026-04-10.md`, `.raw/notion/2026-04-11.md`
- **Pages created**:
  - Concepts: [[ai-coding-agents]], [[llm-wiki-pattern]], [[agent-memory]], [[llm-context-scaling]], [[mcp-ecosystem]]
  - Entities: [[claude-code]], [[claude-obsidian]], [[obra-superpowers]], [[mempalace]]
  - Sources: [[uncomfortable-truths-ai-coding-agents]] (critical take, 2026-03-28 briefing)
  - Meta: [[index]], [[log]], [[hot]]
- **Key insights**:
  - The [[llm-wiki-pattern]] is now a wave, not a fad — 5+ independent implementations in Q2 2026
  - [[agent-memory]] infrastructure is the dominant agent-tooling theme; mempalace at 5,871★/day on 2026-04-11
  - [[llm-context-scaling]] is the competing / complementary thread — MSA hit <9% degradation from 16K to 100M tokens
  - The critical take on AI coding agents ([[uncomfortable-truths-ai-coding-agents]]) is becoming consensus among shipping practitioners
- **Contradictions found**: none significant in this first pass — the Mythos narrative shifted between 2026-03-27 (accidental leak, withholding framing) and 2026-04-11 (controlled Project Glasswing release), flagged in [[.raw/notion/2026-04-11.md|4/11 raw]] but not yet worth a dedicated concept page
- **Gaps noticed**: no daily summary pages yet (`wiki/daily/`); no dedicated page for Project Glasswing / Mythos yet; no `anthropic` entity page yet

## [2026-04-11] bootstrap | vault initialized

- Installed `claude-obsidian` skills, commands, hooks, templates, frontmatter schema as the base
- Cherry-picked `/challenge /synthesize /emerge /graduate /connect` from `obsidian-second-brain`
- Installed `qmd` globally, registered `kb` collection pointing at `wiki/`, added collection context
- Wrote custom `/ingest-notion-briefing` slash command
- Patched `wiki-query` SKILL.md with qmd-first step 0
- Patched `wiki-ingest` SKILL.md with qmd reindex + multimedia (YouTube/audio) + new frontmatter fields
- Extended `skills/wiki/references/frontmatter.md` with `sentiment` / `ingested_via` / `briefing_date`
- Customized `CLAUDE.md` and `CRITICAL_FACTS.md` for mk's identity
- Vault-scoped `.claude/settings.json` registers qmd MCP server + all 4 hooks (SessionStart, PostCompact, PostToolUse auto-commit, Stop prompt)
