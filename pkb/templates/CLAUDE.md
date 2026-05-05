# pkb vault rules

Personal knowledge base powered by pkb-mcp. See the [pkb-mcp README](https://github.com/Miandari/personal-knowledge-base-mcp) for architecture.

## Core rules

1. **Retrieval**: use `kb_explore` first, then `kb_search`. Never grep wiki/ for search — use MCP tools.
2. **Compilation is demand-driven.** Ingestion adds pages and indexes them. Do NOT auto-rewrite pages.
3. **Preserve Obsidian compatibility**: wikilinks, flat YAML frontmatter.
4. **Always reindex after writes.** After every Edit/Write to a wiki/ file, call `kb_reindex`.
5. **Sequential reindex**: never run `kb_reindex` calls in parallel — SQLite locking errors.

## Frontmatter

```yaml
title: "Page title"
origin: note              # webpage|paper|conversation|note|book|transcript|meta
status: seed              # seed|developing|mature|evergreen
tags:
  - topic-tag
related:
  - "[[other-page]]"
sources:
  - "[[source-page]]"
created_at: 2026-01-01
updated_at: 2026-01-01
```

Wikilinks are pathless: `[[agent-memory]]` not `[[concepts/agent-memory]]`.

## CLI

```bash
pkb rebuild [--force] [--no-embed]  # rebuild index
pkb status                          # check health
pkb search "query" [--mode bm25]    # test search
pkb server                          # start MCP server (stdio)
```
