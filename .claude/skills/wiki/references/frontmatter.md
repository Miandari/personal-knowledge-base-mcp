# Frontmatter Schema

Every wiki page starts with flat YAML frontmatter. No nested objects. Obsidian's Properties UI requires flat structure.

---

## Universal Fields

Every page, no exceptions:

```yaml
---
type: <source|entity|concept|domain|comparison|question|overview|meta>
title: "Human-Readable Title"
created: 2026-04-07
updated: 2026-04-07
tags:
  - <domain-tag>
  - <type-tag>
status: <seed|developing|mature|evergreen>
related:
  - "[[Other Page]]"
sources:
  - "[[.raw/articles/source-file.md]]"
# Optional provenance fields — set when applicable, omit otherwise:
sentiment: <critical|skeptical|neutral|mixed|enthusiastic>
ingested_via: <notion_briefing|manual|web_fetch|youtube_mcp>
briefing_date: YYYY-MM-DD
---
```

**status values:**
- `seed`: exists, barely populated
- `developing`: has real content, not yet complete
- `mature`: comprehensive, well-linked
- `evergreen`: unlikely to need updates

**Optional provenance fields** (omit if not applicable — they're universal in the sense that *any* type may carry them):
- `sentiment`: your honest read of how the source or synthesis frames its subject. Use `critical` for red-team / negative takes, `skeptical` for cautious doubt, `neutral` for descriptive, `mixed` for balanced pros-and-cons, `enthusiastic` for boosterism. This field is what makes queries like "critical takes on AI coding agents" actually work — BM25 picks up the word `critical` in the frontmatter text when you ask for critical perspectives.
- `ingested_via`: how this page reached the vault. `notion_briefing` for daily AI dev briefings, `manual` for paste / direct file drops, `web_fetch` for standalone URL ingestion, `youtube_mcp` for YouTube/MCP-driven transcripts.
- `briefing_date`: if this page traces back to a specific daily briefing, the briefing's date in ISO form. Lets you answer "what did I learn on 2026-03-28" without scanning everything.

---

## Type-Specific Additions

### source

Add these fields after the universal fields:

```yaml
source_type: article    # article | video | podcast | paper | book | transcript | data
author: ""
date_published: YYYY-MM-DD
url: ""
confidence: high        # high | medium | low
key_claims:
  - "First key claim from this source"
  - "Second key claim"
```

### entity

```yaml
entity_type: person     # person | organization | product | repository | place
role: ""
first_mentioned: "[[Source Title]]"
```

### concept

```yaml
complexity: intermediate  # basic | intermediate | advanced
domain: ""
aliases:
  - "alternative name"
  - "abbreviation"
```

### comparison

```yaml
subjects:
  - "[[Thing A]]"
  - "[[Thing B]]"
dimensions:
  - "performance"
  - "cost"
  - "ease of use"
verdict: "One-line conclusion."
```

### question

```yaml
question: "The original query as asked."
answer_quality: solid   # draft | solid | definitive
```

### domain

```yaml
subdomain_of: ""        # leave empty for top-level domains
page_count: 0
```

---

## Rules

1. Use flat YAML only. Never nest objects.
2. Dates as `YYYY-MM-DD` strings, not ISO datetime.
3. Lists always use the `- item` format, not inline `[a, b, c]`.
4. Wikilinks in YAML fields must be quoted: `"[[Page Name]]"`.
5. Keep `related` and `sources` as wikilinks, not plain URLs.
6. Update `updated` every time you edit the page content.
7. Prefer to omit optional fields (including `sentiment`, `ingested_via`, `briefing_date`) rather than setting them to empty strings — flat YAML with `sentiment: ""` is worse than no `sentiment` key at all, because BM25 will still index the bare word.
