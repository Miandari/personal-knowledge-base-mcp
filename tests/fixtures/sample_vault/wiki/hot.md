# Hot cache

**Last Updated**: 2026-04-11

## Key Recent Facts

- Vault bootstrapped 2026-04-11 from `AgriciDaniel/claude-obsidian` (base) + 5 cherry-picked thinking tools from `eugeniughelbur/obsidian-second-brain` + `@tobilu/qmd` hybrid search (2.1.0).
- Four daily AI dev briefings ingested on kickoff: 2026-03-27, 2026-03-28, 2026-04-10, 2026-04-11.
- Five concept pages and four entity pages compiled from those briefings. `wiki/sources/uncomfortable-truths-ai-coding-agents.md` is the canonical critical take on AI coding agents and is the retrieval-test target.
- `qmd` MCP server is registered at vault scope. Index rebuilt after initial ingest. Embedding models download on first real query.

## Recent Changes

- **Created** 10 wiki pages (5 concepts, 4 entities, 1 source) + `wiki/index.md` + `wiki/log.md`
- **Patched** `wiki-query/SKILL.md` to try qmd first, fall back to plain file reads
- **Patched** `wiki-ingest/SKILL.md` with qmd reindex + YouTube/audio multimedia handling + new provenance frontmatter fields (`sentiment`, `ingested_via`, `briefing_date`)
- **Extended** frontmatter schema reference
- **Wrote** custom `/ingest-notion-briefing` slash command for the Notion daily briefing workflow

## Active Threads

- **Retrieval test (in progress)**: uncomfortable-truths article must surface on conceptual queries ("critical takes on AI coding agents", "where does Claude Code fall short", "honest problems with current AI coding tools"). Target: ≥2 of 3 in top 5.
- **Additional retrieval tests**: GitHub repos about agent memory (→ [[mempalace]], [[agent-memory]]), latest on MCP server development (→ [[mcp-ecosystem]]), LLM context window scaling (→ [[llm-context-scaling]]).
- **Known gaps**: no `wiki/daily/` summary pages yet, no Anthropic entity page yet, no Project Glasswing / Mythos concept page yet.

## Open Questions

- Will plain BM25 alone be enough to pass the uncomfortable-truths test, or does this need the vector side of qmd fully warmed up?
- Does the PostToolUse auto-commit hook fire when `Write` happens inside a session started before the hook was registered? (Likely no — hooks load at session start.)

## User context (persistent)

- mk is a PhD candidate in computational social science
- Daily reader of the Notion AI/ML dev briefing (parent `318a6df2-0ce4-80bf-ac67-e2a622e47636`)
- Primary interests: agent memory, LLM context scaling, MCP, AI coding agents (including critical takes)
- Uses **both** Obsidian.app and Claude Code against this vault
