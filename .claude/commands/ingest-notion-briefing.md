---
description: Fetch a daily AI dev briefing from Notion and compile it into the wiki. Usage&#58; /ingest-notion-briefing [YYYY-MM-DD] (defaults to today).
---

Ingest a daily AI dev briefing from Notion into the wiki vault.

## Arguments

Optional date in `YYYY-MM-DD` form. If omitted, default to today's date.

## Notion hierarchy

The daily briefing lives in Notion under this tree:

- **Parent page** (`Daily ai dev briefing`): `318a6df2-0ce4-80bf-ac67-e2a622e47636`
- Children are **month pages** titled like `March 2026`, `April 2026`, ...
- Each month page has **day pages** titled `YYYY-MM-DD`

Known month-page IDs (cache as we discover more):
- April 2026 → `337a6df20ce481df9fe7d3e3e2982648`
- March 2026 → discover by fetching the parent

## Workflow

1. **Parse the date argument.** If missing, use today's date in `YYYY-MM-DD` form. Extract the `YYYY-MM` portion to determine the target month name (e.g., `2026-04` → `April 2026`).

2. **Locate the month page.** If we already have its ID cached above, use it directly. Otherwise call `mcp__claude_ai_Notion__notion-fetch` with id `318a6df2-0ce4-80bf-ac67-e2a622e47636` and scan the result for the `<page>` child whose title matches the target month. Save its URL for the next step.

3. **Locate the day page.** Call `mcp__claude_ai_Notion__notion-fetch` with the month page's id. Scan its children for the `<page>` whose title equals the target date (`YYYY-MM-DD`). Grab its id.

4. **If the day page is missing**, tell the user: "No briefing found in Notion for {date}. The most recent available day is {latest}. Want me to ingest that instead?" Stop.

5. **Fetch the day page.** Call `mcp__claude_ai_Notion__notion-fetch` with the day-page id. Capture the full Notion-flavored markdown content.

6. **Write the raw dump.** Save the fetched content to `.raw/notion/YYYY-MM-DD.md`, with a provenance header prepended:
   ```yaml
   ---
   source_type: notion_briefing
   source_url: "https://www.notion.so/{day_page_id_no_dashes}"
   briefing_date: YYYY-MM-DD
   fetched: <today YYYY-MM-DD>
   ingested_via: notion_briefing
   ---

   # Daily AI dev briefing — YYYY-MM-DD

   <full Notion page content below this line, unmodified>
   ```
   Do **not** overwrite an existing `.raw/notion/YYYY-MM-DD.md` unless the user says `force`. Check delta via the `.raw/.manifest.json` tracker (same mechanism `wiki-ingest` uses) before re-processing.

7. **Delegate to wiki-ingest.** Invoke the `wiki-ingest` skill on the raw file path. Pass instructions that every extracted source, entity, and concept page created from this briefing must carry:
   - `ingested_via: notion_briefing`
   - `briefing_date: YYYY-MM-DD`  (the briefing date, not today)
   - `sentiment` should be set for **any** page where the source takes a clear stance — especially critical/skeptical takes, since those are the ones retrieval will ask about later.

8. **Extraction targets.** Tell wiki-ingest to specifically look for and extract:
   - **GitHub repos** (URLs matching `github.com/<owner>/<repo>`) → create or update pages in `wiki/entities/` with `entity_type: repository`
   - **Blog articles / news URLs** → create a page in `wiki/sources/` and fetch the full article body via `WebFetch` (plus `defuddle` cleanup if available) so vector retrieval has real text to match against, not just a URL stub
   - **YouTube videos** → use the wiki-ingest Multimedia Ingestion path (`yt-dlp`) to pull metadata + transcript
   - **Tools / products** named in the briefing → `wiki/entities/` with `entity_type: product`
   - **People** mentioned → `wiki/entities/` with `entity_type: person`
   - **Concepts / claims / trends** → `wiki/concepts/`

9. **Per-day summary page.** After wiki-ingest finishes, create `wiki/daily/YYYY-MM-DD-briefing.md` (make the `daily/` folder if it doesn't exist) that lists in plain markdown:
   - What was ingested from this briefing (titles + wikilinks)
   - Pages touched (created / updated)
   - Any contradictions found vs. earlier briefings
   - One-line "key insight" summarising the day
   Add an entry for it to `wiki/index.md` under a Daily / Briefings section.

10. **Refresh retrieval index.** Run `command -v qmd >/dev/null 2>&1 && qmd update --collection kb && qmd embed -f || true` after everything settles, so the new pages are searchable immediately via `/query`.

11. **Report back.** Print:
    - Briefing date
    - Raw dump path
    - N pages created, M pages updated
    - Any notable entities / repos added
    - Gaps noticed ("no page on X yet — want to find a source?")

## Edge cases

- **Empty briefing** (the Notion page exists but is mostly empty): still create the raw dump, still make the daily summary (mark it as sparse), but don't create phantom wiki pages for content that isn't there.
- **Partial re-ingest**: if the raw dump already exists and the user passed `force`, delete it and re-run. Otherwise skip to step 9 and regenerate only the daily summary / index entry in case those are missing.
- **Notion MCP unavailable**: say so explicitly and stop. This command's entire purpose is Notion-to-wiki — there's no meaningful fallback.
- **Date parsing failure**: if the argument can't be parsed as `YYYY-MM-DD`, prompt the user to pass it in that exact form.
