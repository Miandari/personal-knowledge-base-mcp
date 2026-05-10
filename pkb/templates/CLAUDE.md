# pkb vault rules

Personal knowledge base powered by pkb-mcp. See the [pkb-mcp README](https://github.com/Miandari/personal-knowledge-base-mcp) for architecture.

## Core rules

1. **Retrieval**: use `kb_find` for all reads — search, get page, or browse. Never grep wiki/ directly.
2. **Writes**: use `kb_save` for all writes — create, update, or reindex. It auto-reindexes after every change.
3. **Show before saving**: always draft the proposed title, body, tags, origin, and related links and show them to the user before calling `kb_save`.
4. **Pages are just pages**: no prescribed sections. Pages have whatever structure the user gives them.
5. **Preserve Obsidian compatibility**: wikilinks, flat YAML frontmatter.

## MCP tools

| Tool | Purpose |
|------|---------|
| `kb_find` | Search (query), get page (id), or browse (filters) |
| `kb_save` | Create, update section, update metadata, or reindex pages |
| `kb_status` | Index health check |

## Frontmatter

```yaml
title: "Page title"
origin: note              # webpage|paper|conversation|note|book|transcript|meta
status: seed              # seed|developing|mature|evergreen
ingested_via: manual      # manual|claude_code|claude_ui|notion_briefing|web_fetch|youtube_mcp
aliases:
  - "Alternative Name"
tags:
  - topic-tag
related:
  - "[[other-page]]"
sources:
  - "[[wiki-source-page]]"
raw_sources:
  - ".raw/notion/2026-04-10.md"
created_at: 2026-01-01
updated_at: 2026-01-01
```

- `sources:` — graph edges to wiki pages (pages this was built from)
- `raw_sources:` — provenance pointers to `.raw/` files (NOT graph edges)
- `aliases:` — old names/paths, survive `pkb rebuild --force`
- Wikilinks are pathless: `[[agent-memory]]` not `[[concepts/agent-memory]]`
- Omit optional fields rather than leaving them blank.

## CLI

```bash
pkb rebuild [--force] [--no-embed]  # rebuild index
pkb status                          # check health
pkb search "query" [--mode bm25]    # test search
pkb server                          # start MCP server (stdio)
```
