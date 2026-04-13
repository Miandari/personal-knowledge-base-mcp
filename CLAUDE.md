# pkb — project rules

Personal knowledge base MCP server. See @README.md for architecture and design rationale.
User context is in auto-memory (`~/.claude/projects/.../memory/`).

## Key directories

- `.raw/` — **immutable** source material. Never edit after first write.
- `wiki/` — compiled knowledge. Rewriteable. This is the product.
- `pkb/` — Python package (SQLite backend, indexer, search, MCP server).
- `.claude/skills/` — copies of upstream repos. Use `bin/resync-claude-obsidian.sh` to update.

## Core rules

1. **Retrieval**: use `kb_explore` first, then `kb_search`. Never grep `wiki/**` for search/retrieval — use the MCP tools. Direct file reads for editing are fine.
2. **Compilation is demand-driven.** Ingestion adds pages and indexes them. Do NOT auto-rewrite concept pages — `kb_explore` detects staleness and the user decides when to compile.
3. **Two-output rule**: if you learned something worth remembering, file it (`/save` or wiki page).
4. **Preserve Obsidian compatibility**: wikilinks, flat YAML frontmatter, don't break `.obsidian/` or `_templates/`.
5. **Always reindex after writes.** After every Edit/Write to a `wiki/` file, call `kb_reindex` on that file before doing anything else. Skipping this is the #1 cause of stale search results.
6. **Sequential reindex**: never run `kb_reindex` calls in parallel — SQLite locking errors.

## Frontmatter

Full schema: `.claude/skills/wiki/references/frontmatter.md`. Key vault-specific fields:

- `sentiment` — `critical | skeptical | neutral | mixed | enthusiastic`. Set when a source takes a stance.
- `ingested_via` — `notion_briefing | manual | web_fetch | youtube_mcp`.
- `briefing_date` — originating briefing day (if from a daily briefing).

Omit optional fields rather than leaving them blank.

## Hot cache

- `wiki/hot.md` loads at session start and after compaction (via hooks).
- The `Stop` hook prints `WIKI_CHANGED: ...` when wiki files were modified. When you see that message, **rewrite `wiki/hot.md` completely** with `Last Updated`, `Key Recent Facts`, `Recent Changes`, `Active Threads`. Overwrite, don't append. Under 500 words.

## Auto-commit

A PostToolUse hook runs `git add wiki/ .raw/ && git commit` after every Write/Edit. Don't commit `wiki/` manually during ingests. For structural changes (skills, schema, this file), commit manually with a real message.

## CLI

```bash
python -m pkb rebuild [--force] [--no-embed]  # rebuild index from markdown
python -m pkb status                           # check index health
python -m pkb search "query" [--mode bm25]     # test search
python -m pkb server                           # start MCP server (stdio)
python -m pkb server --transport http --port 8181  # HTTP transport
```

## Testing

```bash
pip install -e ".[test]"
python -m pytest tests/ -v                     # full suite (231 tests)
python -m pytest tests/test_mcp_comprehensive.py -v  # MCP tools + HTTP + auth
```

## Troubleshooting

- Low/zero search results → `python -m pkb status`, check embedding coverage. Run `python -m pkb rebuild` if needed.
- Pages not in search → only `wiki/` is indexed. Files in `.raw/` are not. Run `python -m pkb rebuild`.
- Force full re-index → `python -m pkb rebuild --force`.
