---
name: wiki-ingest
description: "Ingest sources into the Obsidian wiki vault. Handles URLs, files, images, YouTube videos, audio files, and batch mode. Extracts entities and concepts, creates or updates wiki pages, cross-references, logs the operation, and refreshes the SQLite search index. Triggers on: ingest, process this source, add this to the wiki, read and file this, batch ingest, ingest all of these, ingest this url, ingest this video, transcribe and ingest."
---

# wiki-ingest: Source Ingestion

Read the source. Write the wiki. Cross-reference everything. A single source typically touches 8-15 wiki pages.

**Syntax standard**: Write all Obsidian Markdown using proper Obsidian Flavored Markdown. Wikilinks as `[[Note Name]]`, callouts as `> [!type] Title`, embeds as `![[file]]`, properties as YAML frontmatter. If the kepano/obsidian-skills plugin is installed, prefer its canonical obsidian-markdown skill for Obsidian syntax reference. Otherwise, follow the guidance in this skill.

---

## Delta Tracking

Before ingesting any file, check `.raw/.manifest.json` to avoid re-processing unchanged sources.

```bash
# Check if manifest exists
[ -f .raw/.manifest.json ] && echo "exists" || echo "no manifest yet"
```

**Manifest format** (create if missing):
```json
{
  "sources": {
    ".raw/articles/article-slug-2026-04-08.md": {
      "hash": "abc123",
      "ingested_at": "2026-04-08",
      "pages_created": ["wiki/sources/article-slug.md", "wiki/entities/Person.md"],
      "pages_updated": ["wiki/index.md"]
    }
  }
}
```

**Before ingesting a file:**
1. Compute a hash: `md5sum [file] | cut -d' ' -f1` (or `sha256sum` on Linux).
2. Check if the path exists in `.manifest.json` with the same hash.
3. If hash matches, skip. Report: "Already ingested (unchanged). Use `force` to re-ingest."
4. If missing or hash differs, proceed with ingest.

**After ingesting a file:**
1. Record `{hash, ingested_at, pages_created, pages_updated}` in `.manifest.json`.
2. Write the updated manifest back.

Skip delta checking if the user says "force ingest" or "re-ingest".

---

## URL Ingestion

Trigger: user passes a URL starting with `https://`.

Steps:

1. **Fetch** the page using WebFetch.
2. **Clean** (optional): if `defuddle` is available (`which defuddle 2>/dev/null`), run `defuddle [url]` to strip ads, nav, and clutter. Typically saves 40-60% tokens. Fall back to raw WebFetch output if not installed.
3. **Derive slug** from the URL path (last segment, lowercased, spaces→hyphens, strip query strings).
4. **Save** to `.raw/articles/[slug]-[YYYY-MM-DD].md` with a frontmatter header:
   ```markdown
   ---
   source_url: [url]
   fetched: [YYYY-MM-DD]
   ---
   ```
5. Proceed with **Single Source Ingest** starting at step 2 (file is now in `.raw/`).

---

## Image / Vision Ingestion

Trigger: user passes an image file path (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`, `.avif`).

Steps:

1. **Read** the image file using the Read tool. Claude can process images natively.
2. **Describe** the image contents: extract all text (OCR), identify key concepts, entities, diagrams, and data visible in the image.
3. **Save** the description to `.raw/images/[slug]-[YYYY-MM-DD].md`:
   ```markdown
   ---
   source_type: image
   original_file: [original path]
   fetched: YYYY-MM-DD
   ---
   # Image: [slug]

   [Full description of image contents, transcribed text, entities visible, etc.]
   ```
4. Copy the image to `_attachments/images/[slug].[ext]` if it's not already in the vault.
5. Proceed with **Single Source Ingest** on the saved description file.

Use cases: whiteboard photos, screenshots, diagrams, infographics, document scans.

---

## Multimedia Ingestion (YouTube + audio)

Trigger: user passes a YouTube URL, or an audio file (`.m4a`, `.mp3`, `.wav`, `.ogg`, `.webm`, `.flac`).

### YouTube URLs

Try methods in order; use the first one that works.

**Method A — `yt-dlp` (preferred, works in Claude Code / terminal):**
```bash
which yt-dlp || brew install yt-dlp
yt-dlp --skip-download \
       --print title --print description --print duration_string \
       --print view_count --print like_count --print upload_date --print channel \
       "<URL>"
yt-dlp --write-auto-sub --sub-lang en --skip-download -o "/tmp/%(id)s" "<URL>"
```
The `.en.vtt` file in `/tmp/` is the auto-generated transcript.

**Method B — YouTube MCP tools**: if MCP tools expose YouTube transcript fetching, use them.

**Method C — oEmbed fallback** (limited data, last resort):
```bash
curl -s "https://www.youtube.com/oembed?url=<URL>&format=json"
```
Returns title + channel only. Ask the user to paste the description or transcript.

After fetching: save to `.raw/videos/<video-id>-<YYYY-MM-DD>.md` with frontmatter:
```yaml
---
source_type: video
source_url: "<URL>"
title: "<title>"
channel: "<channel>"
upload_date: YYYY-MM-DD
duration: "<mm:ss or hh:mm:ss>"
fetched: YYYY-MM-DD
ingested_via: youtube_mcp   # or manual
---
```
Then proceed with **Single Source Ingest** starting at step 2.

### Audio files

```bash
# Transcribe with Whisper (install if missing)
which whisper || pip install openai-whisper
whisper "<path/to/audio>" --model base --output_format txt --output_dir /tmp
```

If `whisper` can't be installed, ask the user to paste the transcript.

After transcription:
- Identify speakers where possible
- Extract decisions, action items, quotes, promises
- Save to `.raw/transcripts/<slug>-<YYYY-MM-DD>.md` with `source_type: transcript` frontmatter
- Proceed with **Single Source Ingest**

> These blocks are ported from `eugeniughelbur/obsidian-second-brain/commands/obsidian-ingest.md` (MIT). Upstream may evolve — see `bin/resync-claude-obsidian.sh` caveats.

---

## Single Source Ingest

Trigger: user drops a file into `.raw/` or pastes content.

Steps:

1. **Read** the source completely. Do not skim.
2. **Discuss** key takeaways with the user. Ask: "What should I emphasize? How granular?" Skip this if the user says "just ingest it."
3. **Create the page** using `kb_add`:
   - Determine `type` (source, entity, concept) from the content
   - Extract `title`, `tags`, `sentiment`, `source_url` from the source
   - Write the markdown body following the frontmatter schema from `references/frontmatter.md`
   - Set these briefing-aware universal fields when applicable:
     - `sentiment`: one of `critical | skeptical | neutral | mixed | enthusiastic` — your honest read of how the source frames its subject. Omit if genuinely neutral / N/A.
     - `ingested_via`: one of `notion_briefing | manual | web_fetch | youtube_mcp` — how this source reached the vault.
   - Call: `kb_add(title=..., type=..., body=..., tags=[...], source_url=..., sentiment=..., ingested_via=...)`
   - `kb_add` writes the file AND indexes it immediately. The page is searchable right away.
4. **Update `wiki/index.md`** — add an entry for the new page.
5. **Append** to `wiki/log.md` (new entries at the TOP):
    ```markdown
    ## [YYYY-MM-DD] ingest | Source Title
    - Source: `.raw/articles/filename.md`
    - Summary: [[Source Title]]
    - Pages created: [[Page 1]]
    - Key insight: One sentence on what is new.
    ```
6. **Reindex meta pages** — you MUST execute these calls sequentially, one at a time. Do not run indexing tools in parallel (concurrent writes cause database locking errors):
   - First: `kb_reindex(file_path="wiki/index.md")`
   - Then: `kb_reindex(file_path="wiki/log.md")`
7. **Check for contradictions** against existing pages. If found, add `> [!contradiction]` callouts on both pages. After editing any existing page, call `kb_reindex(file_path=...)` on it before proceeding.
8. **Offer to explore**: "Added [[page-title]] as a seed page. Run `explore: <topic>` to see what it connects to and whether related concept pages need recompilation."

---

## Batch Ingest

Trigger: user drops multiple files or says "ingest all of these."

Steps:

1. List all files to process. Confirm with user before starting.
2. Process each source following the single ingest flow. Defer cross-referencing between sources until step 3.
3. After all sources: do a cross-reference pass. Look for connections between the newly ingested sources.
4. Update index, hot cache, and log once at the end (not per-source). Reindex meta pages sequentially (one `kb_reindex` at a time — no parallel calls).
5. Report: "Processed N sources. Created X pages, updated Y pages. Here are the key connections I found."

Batch ingest is less interactive. For 30+ sources, expect significant processing time. Check in with the user after every 10 sources.

---

## Context Window Discipline

Token budget matters. Follow these rules during ingest:

- Read `wiki/hot.md` first. If it contains the relevant context, don't re-read full pages.
- Read `wiki/index.md` to find existing pages before creating new ones.
- Read only 3-5 existing pages per ingest. If you need 10+, you are reading too broadly.
- Use PATCH for surgical edits. Never re-read an entire file just to update one field.
- Keep wiki pages short. 100-300 lines max. If a page grows beyond 300 lines, split it.
- Use search (`/search/simple/`) to find specific content without reading full pages.

---

## Contradictions

> [!note] Custom callout dependency
> The `[!contradiction]` callout type used below is a **custom callout** defined in `.obsidian/snippets/vault-colors.css` (auto-installed by `/wiki` scaffold). It renders with reddish-brown styling and an alert-triangle icon when the snippet is enabled. If the snippet is missing, Obsidian falls back to default callout styling, so the page still works without the visual flourish. See [[skills/wiki/references/css-snippets.md]] for the four custom callouts (`contradiction`, `gap`, `key-insight`, `stale`).

When new info contradicts an existing wiki page:

On the existing page, add:
```markdown
> [!contradiction] Conflict with [[New Source]]
> [[Existing Page]] claims X. [[New Source]] says Y.
> Needs resolution. Check dates, context, and primary sources.
```

On the new source summary, reference it:
```markdown
> [!contradiction] Contradicts [[Existing Page]]
> This source says Y, but existing wiki says X. See [[Existing Page]] for details.
```

Do not silently overwrite old claims. Flag and let the user decide.

---

## What Not to Do

- Do not modify anything in `.raw/`. These are immutable source documents.
- Do not create duplicate pages. Always check the index and search before creating.
- Do not skip the log entry. Every ingest must be recorded.
- Do not skip the hot cache update. It is what keeps future sessions fast.
