# pkb vault rules

Personal knowledge base powered by pkb-mcp. See the [pkb-mcp README](https://github.com/Miandari/personal-knowledge-base-mcp) for architecture.

## Core rules

1. **Retrieval**: use `kb_explore` first, then `kb_search`. Never grep wiki/ for search — use MCP tools.
2. **Compilation is demand-driven.** Ingestion adds pages. Do NOT auto-rewrite pages — `kb_explore` detects staleness and the user decides when to compile.
3. **Preserve Obsidian compatibility**: wikilinks, flat YAML frontmatter.
4. **Always reindex after writes.** After every Edit/Write to a wiki/ file, call `kb_reindex`.
5. **Sequential reindex**: never run `kb_reindex` calls in parallel — SQLite locking errors.

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

- `sources:` — graph edges to wiki pages (used by explore/synthesis detection)
- `raw_sources:` — provenance pointers to `.raw/` files (NOT graph edges)
- `aliases:` — old names/paths, survive `pkb rebuild --force`
- Wikilinks are pathless: `[[agent-memory]]` not `[[concepts/agent-memory]]`
- Omit optional fields rather than leaving them blank.

## Page structure

Pages can have a `## Notes` section (user content) and a `## Synthesis` section (compiled by LLM). During compilation, only `## Synthesis` is rewritten — `## Notes` is preserved.

## CLI

```bash
pkb rebuild [--force] [--no-embed]  # rebuild index
pkb status                          # check health
pkb search "query" [--mode bm25]    # test search
pkb server                          # start MCP server (stdio)
```
