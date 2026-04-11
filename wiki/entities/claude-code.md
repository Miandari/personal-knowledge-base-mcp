---
type: entity
title: "Claude Code"
created: 2026-04-11
updated: 2026-04-11
tags:
  - ai-coding-agents
  - tool
  - anthropic
  - claude-code
status: developing
entity_type: product
role: "Anthropic's terminal-native AI coding agent (CLI)"
first_mentioned: "[[.raw/notion/2026-03-27.md]]"
related:
  - "[[anthropic]]"
  - "[[ai-coding-agents]]"
  - "[[uncomfortable-truths-ai-coding-agents]]"
  - "[[obra-superpowers]]"
  - "[[claude-obsidian]]"
sources:
  - "[[.raw/notion/2026-03-27.md]]"
  - "[[.raw/notion/2026-03-28.md]]"
  - "[[.raw/notion/2026-04-10.md]]"
  - "[[.raw/notion/2026-04-11.md]]"
---

# Claude Code

Anthropic's CLI-based AI coding agent. The user interacts with it daily — this vault itself runs under Claude Code.

## Recent releases observed in briefings

| Version | Date | Notable |
|---|---|---|
| v2.1.85 | 2026-03-26 | MCP, hook, and plugin workflow improvements. Environment variables for MCP server config. Conditional hook filtering. Deep link support expanded to 5,000 chars. Context compaction, keyboard, multi-monitor fixes. ~30ms startup improvement. ([[.raw/notion/2026-03-27.md]]) |
| v2.1.84 | 2026-03-26 | Windows PowerShell preview. Environment variables for model detection. New hook events. Managed settings for plugin allowlisting. Voice mode + MCP server stability fixes. ([[.raw/notion/2026-03-27.md]]) |
| v2.1.86 | 2026-03-27 | `X-Claude-Code-Session-Id` header for proxy aggregation. `.jj` and `.sl` added to VCS exclusion lists (Jujutsu + Sapling support). Fixed `--resume` on pre-v2.1.85 sessions. Fixed Write/Edit/Read failing on files outside project root when conditional skills/rules configured. ([[.raw/notion/2026-03-28.md]]) |
| v2.1.97 | ~2026-04-10 | Buddy Mode removal. ([[.raw/notion/2026-04-11.md]]) |

## Known issues

- **Windows support is neglected.** r/ClaudeAI thread on 2026-03-28 (157↑, 149 comments) documents 6 critical Windows/WSL2 bugs closed as "not planned" — widely-shared frustration. VS Code + WSL2 pain points in particular. ([[.raw/notion/2026-03-28.md]])
- **Rate limits are dynamic during peak hours.** Anthropic confirmed on 2026-03-27 that the "rate limit bug" was actually peak-hour dynamic token pricing (05:00–11:00 PT). ~7% of users affected, mostly Pro tier. Off-peak limits doubled for two weeks as compensation. Community backlash intensified rather than subsided. ([[.raw/notion/2026-03-27.md]], [[.raw/notion/2026-03-28.md]])
- **Token inflation.** Claude responses have gotten longer, effectively reducing exchanges per session (r/ClaudeAI, 145↑ on 2026-03-27). ([[.raw/notion/2026-03-27.md]])
- **Plugin hook STDOUT bug** `anthropics/claude-code#10875` — plugin hooks may not capture STDOUT, while identical hooks in `settings.json` work. Workaround: use vault-local or user-level `settings.json`, not plugin distribution.
- **Production-readiness critique.** See [[uncomfortable-truths-ai-coding-agents]] for the clearest articulation of where Claude Code (and peers) fall short in production environments — institutional-context gap, architectural drift, silent performance regressions.

## Ecosystem around Claude Code

- [[obra-superpowers]] — composable `SKILL.md` framework + TDD methodology. #1 trending GitHub repo on 2026-03-28 (120k⭐, 2.3k stars/day). The de-facto skills-based methodology.
- [[claude-obsidian]] — LLM-wiki plugin and vault template. The base we built this vault from.
- `JuliusBrussee/caveman` — token-compression skill, ~65% output token reduction by rewriting prompts in terse style. 16k⭐.
- `coleam00/claude-memory-compiler` — compiles codebase-interaction history into an evolving memory layer.
- `Houseofmvps/codesight` — project-context bundle generator for Claude Code / Cursor / Copilot.

## Related entities and concepts

- [[anthropic]] — parent company
- [[ai-coding-agents]] — the concept page this product instantiates
- [[mcp-ecosystem]] — the protocol Claude Code uses to talk to tools
- [[advisor-strategy]] — the Opus-planner + Sonnet/Haiku-executor pattern, now API-native
