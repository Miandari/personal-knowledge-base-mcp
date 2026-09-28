# Frontmatter Schema

Every wiki page starts with flat YAML frontmatter. No nested objects. Obsidian's Properties UI requires flat structure.

---

## Required Fields

Every page, no exceptions:

```yaml
---
title: "Human-Readable Title"
origin: note                    # webpage|paper|conversation|note|book|transcript|meta|synthesis
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
- `note`: personal notes and observations
- `book`: book summaries or excerpts
- `transcript`: video/audio transcripts (YouTube, podcasts)
- `meta`: structural pages (index, log)
- `synthesis`: composed in one run from several sources — a field map, a sweep, a comparison. See **Synthesis sources** below.

`kb_save` rejects any other value.

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

### Synthesis sources

Whoever writes a synthesis records everything it drew on, as completely as it can:

- Every existing wiki page the run used → `sources:`. This is what lets `kb_find` report `stale_sources` (inputs updated since) and `new_since` (newer pages not yet linked).
- Everything else it used (papers, posts, talks, repos with no wiki page) → a `## Sources` section at the end of the body, one line each with a link. Never put URLs in `sources:`.
- Pages it only mentions or sits next to → `related:`.
- Sources point back in time: never list a page written after this one; that page should list the synthesis instead. Two pages that source each other mark each other stale on every edit.

An incomplete list makes a synthesis look current when it isn't.

---

## Rules

1. Use flat YAML only. Never nest objects.
2. Dates as `YYYY-MM-DD` strings, not ISO datetime.
3. Lists always use the `- item` format, not inline `[a, b, c]`.
4. Wikilinks in YAML fields must be quoted: `"[[Page Name]]"`.
5. Keep `related` and `sources` as wikilinks, not plain URLs.
6. Update `updated_at` every time you edit the page content.
7. Prefer to omit optional fields rather than setting them to empty strings.
