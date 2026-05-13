---
title: Legacy briefing fixture (briefing_date only, no published_at)
origin: webpage
status: seed
ingested_via: notion_briefing
briefing_date: 2026-03-28
sentiment: neutral
tags:
  - test-fixture
related: []
sources: []
created_at: 2026-03-28
updated_at: 2026-03-28
---

# Legacy briefing fixture

This page intentionally carries only `briefing_date` and not `published_at`,
to exercise the indexer's legacy-fallback path. After indexing, the DB's
`published_at` column should be populated from `briefing_date` via
`fm.get("published_at") or fm.get("briefing_date")` in `_upsert_node`.

Tests can `kb_find(id="legacy-briefing")` and assert that `published_at`
in the result equals `"2026-03-28"`.
