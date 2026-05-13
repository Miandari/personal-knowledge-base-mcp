# Frontmatter Schema

Every wiki page starts with flat YAML frontmatter. No nested objects. Obsidian's Properties UI requires flat structure.

---

## Required Fields

Every page, no exceptions:

```yaml
---
title: "Human-Readable Title"
origin: note                    # webpage|paper|conversation|note|book|transcript|meta
status: developing              # seed|developing|mature|evergreen
tags:
  - topic-tag
related:
  - "[[other-page]]"
sources:
  - "[[source-page]]"
created_at: 2026-05-05
updated_at: 2026-05-05
---
```

**origin values** — provenance, not structural role:
- `webpage`: articles, blog posts, docs, forum posts, READMEs
- `paper`: academic papers
- `conversation`: created during a conversation with an LLM
- `note`: personal notes, observations, synthesis pages
- `book`: book summaries or excerpts
- `transcript`: video/audio transcripts (YouTube, podcasts)
- `meta`: structural pages (index, log)

**status values:**
- `seed`: exists, barely populated
- `developing`: has real content, not yet complete
- `mature`: comprehensive, well-linked
- `evergreen`: unlikely to need updates

## Optional Fields

Omit if not applicable — empty strings are worse than missing keys (BM25 indexes the bare word).

```yaml
# Provenance
ingested_via: manual            # manual|claude_code|claude_ui|notion_briefing|web_fetch|youtube_mcp
raw_sources:                    # provenance pointers to .raw/ files (NOT graph edges)
  - ".raw/notion/2026-04-10.md"

# Content metadata
sentiment: critical             # critical|skeptical|neutral|mixed|enthusiastic
confidence: high                # high|medium|low
complexity: intermediate        # basic|intermediate|advanced
domain: ai-development

# Source-specific
author: "Author Name"
published_at: 2026-03-26        # source's own publication date — accepts YYYY, YYYY-MM, or YYYY-MM-DD; pkb preserves the precision you specify
url: "https://..."
key_claims:
  - "First key claim"
  - "Second key claim"

# Entity-specific
role: "Description of what this entity is/does"
first_mentioned: "[[source-page]]"

# Aliases (survive rebuild --force)
aliases:
  - "Alternative Name"
  - "old/path/from/migration"
```

## Edges

- `sources:` — wiki pages this was built from. Creates `source` edges in the graph. Used by explore for synthesis detection and staleness.
- `related:` — wiki pages this is relevant to. Creates `related` edges. Pages with `related: [[X]]` surface as unincorporated sources when X is explored.
- `raw_sources:` — `.raw/` file provenance. NOT extracted as graph edges. Preserved for traceability only.
- Body `[[wikilinks]]` — automatically extracted as `link` edges during indexing.

All wikilinks are pathless: `[[agent-memory]]` not `[[concepts/agent-memory]]`.

---

## Rules

1. Use flat YAML only. Never nest objects.
2. Dates as `YYYY-MM-DD` strings, not ISO datetime.
3. Lists always use the `- item` format, not inline `[a, b, c]`.
4. Wikilinks in YAML fields must be quoted: `"[[Page Name]]"`.
5. Keep `related` and `sources` as wikilinks, not plain URLs.
6. Update `updated_at` every time you edit the page content.
7. Prefer to omit optional fields rather than setting them to empty strings.
