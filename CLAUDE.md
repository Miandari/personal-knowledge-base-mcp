# compiled-knowledge-base — operating manual

This is a **personal, general-purpose LLM Wiki** for mk. Anything worth remembering — articles, papers, videos, GitHub repos, books, voice notes, conversations, thoughts — can live here, get compiled into synthesized pages, and be retrieved later from any LLM-enabled tool that speaks MCP or a shell. It is built on claude-obsidian skills, a handful of thinking tools from obsidian-second-brain, and `qmd` hybrid search. It is simultaneously an Obsidian vault, a Claude Code project, and an MCP-accessible retrieval target. Read `CRITICAL_FACTS.md` for the ~120-token identity block that is always in context.

## What this vault is (and what it is not)

**It is:**
- **A general knowledge base.** The ingestion pipeline accepts URLs, blog posts, PDFs, images (with OCR), YouTube videos, audio files, raw text, pasted content, Notion pages, and anything else you can hand the `wiki-ingest` skill. There is nothing Notion-specific about the retrieval side.
- **A multi-tool knowledge base.** The underlying store is plain markdown, so Obsidian.app, `grep`, any editor, and any LLM can read it directly. The hybrid-search layer (`qmd`) exposes itself as an MCP server over stdio (and HTTP on demand), so Claude Code, Claude Desktop, Cursor, Cline, Zed, or any other MCP-capable client can query the same index without re-ingesting anything.
- **A compounding knowledge base.** Every ingest **rewrites** existing pages rather than just appending. The vault gets smarter, not just bigger.

**It is not:**
- Notion-only. The daily AI dev briefing from Notion is an *ongoing* ingestion source and the one that kicked this vault off, but it's one workflow among many. `/ingest-notion-briefing` is a 50-line glue skill over the general `wiki-ingest` engine — any other source type can get the same treatment in roughly the same amount of code.
- Claude-Code-only. The MCP server decouples retrieval from the calling agent.
- A dumping ground. If an ingest only creates pages and doesn't rewrite anything, it wasn't deep enough.

## Who you're working with

- mk is a **PhD candidate in computational social science**. Frame technical explanations in terms of research infrastructure, methods, and reproducibility where relevant — not just plain software engineering.
- Primary topic interests right now: **agent memory**, **LLM context scaling**, **MCP server development**, **AI coding agents** (including critical perspectives), computational social science methods. These interests will evolve — don't treat them as a ceiling on what belongs in the vault.
- Current ingestion sources in regular use: daily AI/ML dev briefings from Notion, web articles, occasional YouTube deep-dives, GitHub repos, research papers. Expect this list to grow.
- The vault is used from **both** Claude Code and Obsidian.app (and eventually other MCP clients) — don't break Obsidian-specific files (`.obsidian/`, `_templates/`, wikilink syntax, flat YAML frontmatter).

## Vault structure

```
.raw/               immutable source material (never modify after save)
  notion/           pages pulled from Notion (daily briefings, but any Notion page)
  articles/         fetched blog posts / web pages
  papers/           PDFs and arxiv papers
  videos/           YouTube metadata + transcripts
  transcripts/      audio transcripts (whisper, etc.)
  images/           image sources with OCR descriptions
  text/             raw pasted content, conversation dumps, etc.
  (add more subfolders as new source types emerge — the pipeline doesn't care)
.claude/
  skills/           wiki, wiki-ingest, wiki-query, wiki-lint, save, autoresearch, ...
  commands/         /wiki /save /ingest-notion-briefing /challenge /synthesize /emerge /graduate /connect ...
  settings.json     qmd MCP server + hooks (project-scoped)
wiki/               the knowledge base — Claude-written, rewriteable, indexed by qmd
  hot.md            ~500-token hot cache, read first in every session
  index.md          master navigation
  log.md            append-only operation log (newest first)
  concepts/         ideas, frameworks, synthesis pages
  entities/         people, orgs, products, repositories, tools
  sources/          one page per ingested source
  questions/        filed answers from /query
  daily/            per-day summaries when a day's worth of content gets ingested together
  meta/             vault meta (tag registry, schema notes)
_templates/         concept, entity, source, question, comparison
hooks/              hook shell command sources
bin/                resync + maintenance scripts
tests/              (future) automated test suite for the KB itself
CRITICAL_FACTS.md   always-loaded identity block (~120 tokens)
CLAUDE.md           this file
```

The `.raw/` subfolders are **conventions, not constraints**. `wiki-ingest` will happily take a file from anywhere in `.raw/` and do the right thing. If you start ingesting a new source type, pick a folder name that matches, add it, and move on.

## Core principle: compilation over retrieval

When a new source comes in, **rewrite existing pages** to incorporate it. Do not just append a new page. A vault that only grows is a dumping ground; a vault that gets smarter with every ingest is a second brain. `wiki-ingest` enforces this — read its SKILL.md before ingesting anything substantial.

The two-output rule: every answer also updates the vault. If you learned something in the current conversation worth remembering, file it (`/save` or write a wiki page directly).

## Ingestion protocol

Every source type routes through the same `wiki-ingest` skill. The skill knows how to handle:

- **URLs** — `WebFetch` + optional `defuddle` cleanup to strip ads/nav/boilerplate
- **Images** — read natively (OCR + description), copied to `_attachments/`
- **YouTube videos** — `yt-dlp` for metadata + auto-captions transcript, or YouTube MCP if configured
- **Audio files** — `whisper` transcription with speaker identification where possible
- **PDFs / papers** — read the file directly, extract structure, findings, recommendations
- **Raw text / pasted content** — classify and ingest in place
- **Anything in `.raw/`** — drop a file, say "ingest it," done

Every ingest:
1. Writes the raw source to `.raw/<type>/<slug>-<date>.md` (immutable)
2. Updates `.raw/.manifest.json` for delta tracking (skip re-processing unchanged sources)
3. Creates / rewrites entity pages, concept pages, and the source summary page
4. Resolves contradictions with existing pages via `> [!contradiction]` callouts
5. Updates `wiki/index.md`, `wiki/log.md`, `wiki/hot.md`
6. Refreshes the `qmd` hybrid index so the new content is searchable immediately

Thin wrappers exist for specific common workflows and can be added freely. Current:

| Wrapper | Delegates to | When to use |
|---|---|---|
| `/ingest-notion-briefing [YYYY-MM-DD]` | `wiki-ingest` | Daily AI dev briefings from the Notion parent page `318a6df2-0ce4-80bf-ac67-e2a622e47636` |
| `ingest <file-or-url>` | `wiki-ingest` directly | Everything else — default path |

Any new ingestion wrapper is ~50 lines of glue: fetch the source, write `.raw/<type>/...md` with provenance frontmatter, invoke `wiki-ingest`. Don't reinvent the compilation engine.

## Retrieval protocol

Use `wiki-query` for all non-trivial questions about the vault. It already knows how to try qmd first and fall back to plain file reads. **Do not** reach for `Grep` on `wiki/**` directly unless qmd is unavailable AND `wiki-query` is unavailable.

For direct qmd calls when you're scripting:

```bash
qmd query "<natural-language question>" -c kb --json -n 15
qmd get "#<docid>" --full
```

Or via the MCP server — tools `mcp__qmd__query`, `mcp__qmd__get`, `mcp__qmd__multi_get`, `mcp__qmd__status`.

**Multi-client access.** The qmd MCP server is the single source of truth for retrieval, regardless of which tool you're calling from:

- **Claude Code** (this project) — wired via vault `.claude/settings.json`
- **Claude Desktop** — add `{"mcpServers": {"qmd": {"command": "qmd", "args": ["mcp"]}}}` to `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Cursor / Cline / Zed / any MCP client** — same one-line config
- **HTTP / remote** — `qmd mcp --http --daemon` exposes it on `localhost:8181` for MCP Streamable HTTP clients
- **Shell / scripts / cron** — `qmd query "..." --json` from any shell

The wiki is also **plain markdown**, so even without qmd any LLM that can read files can work against this KB directly.

## Hot cache protocol

- `wiki/hot.md` is loaded automatically at session start (SessionStart hook in `.claude/settings.json` runs `cat wiki/hot.md`).
- After compaction, a PostCompact prompt hook tells you to re-read it.
- At the end of a response that touched `wiki/`, a Stop hook prints `WIKI_CHANGED: ...` — when you see that, **rewrite `wiki/hot.md` completely** with the format: `Last Updated`, `Key Recent Facts`, `Recent Changes`, `Active Threads`. Overwrite, don't append. Keep under 500 words.
- Hot cache is a **cache**, not a journal. The journal is `wiki/log.md`.

## Auto-commit protocol

A PostToolUse hook runs `git add wiki/ .raw/` + `git commit` after every `Write` or `Edit`. You don't need to commit manually for ingests. The message format is `wiki: auto-commit YYYY-MM-DD HH:MM`.

For structural or multi-file changes (new skills, patches to this file, schema changes), commit manually with a real message.

## Notion briefing workflow (one ingestion wrapper among many)

The daily AI dev briefing in Notion is the first regularly-scheduled ingestion source. It is organised as:
`Daily ai dev briefing` (parent `318a6df2-0ce4-80bf-ac67-e2a622e47636`) → month pages → day pages titled `YYYY-MM-DD`.

To ingest a day:
```
/ingest-notion-briefing 2026-04-11
```
or just `/ingest-notion-briefing` for today.

The command fetches via the already-connected Notion MCP, writes `.raw/notion/YYYY-MM-DD.md`, then delegates to `wiki-ingest`. Every resulting page gets `ingested_via: notion_briefing` and `briefing_date: YYYY-MM-DD` in its frontmatter. This is what makes temporal queries like "what did I learn on 2026-03-28" and retrospective queries like "critical takes on AI coding agents from recent briefings" actually work.

This wrapper is the template for any future scheduled or source-specific ingestion skill. Paper ingestion (`/ingest-paper <arxiv-id>`), RSS ingestion, Twitter/X bookmark ingestion, Kindle highlight ingestion, podcast episode ingestion — all would follow the same pattern: small glue command → write to `.raw/<type>/` → delegate to `wiki-ingest`.

## Frontmatter schema

See `.claude/skills/wiki/references/frontmatter.md` for the full schema. Key additions for this vault (over the claude-obsidian default):

- `sentiment` — `critical | skeptical | neutral | mixed | enthusiastic`. Set it whenever a source takes a clear stance. Retrieval queries for "critical takes on X" rely on BM25 matching `critical` inside frontmatter text.
- `ingested_via` — `notion_briefing | manual | web_fetch | youtube_mcp`.
- `briefing_date` — the originating briefing day, if applicable.

Omit optional fields rather than leaving them blank. `sentiment: ""` is worse than no `sentiment` key.

## Commands cheatsheet

**General-purpose (use these by default):**

| Command | What it does |
|---|---|
| `ingest <file-or-url>` | Generic ingest via `wiki-ingest` — URLs, files, images, YouTube, audio, pasted text |
| `query: <question>` | Retrieval via `wiki-query` (qmd-first hybrid search) |
| `/save` | File current conversation as a wiki note |
| `/wiki` | Scaffold / route to sub-skills, health status |

**Source-specific wrappers** (grow this list as new scheduled or repeat sources emerge):

| Command | What it does |
|---|---|
| `/ingest-notion-briefing [YYYY-MM-DD]` | Fetch a daily AI dev briefing from Notion and compile (custom to this vault) |

**Autonomous + thinking tools:**

| Command | What it does |
|---|---|
| `/autoresearch <topic>` | Autonomous research loop — search, fetch, synthesize, file |
| `/canvas` | Visual layer on top of the wiki (Obsidian canvas) |
| `/challenge [idea]` | Red-team the current thinking against vault history |
| `/synthesize` | Scan for unnamed patterns across recent sources |
| `/emerge` | Surface unnamed patterns from the last 30 days |
| `/graduate` | Promote an idea fragment to a full project page |
| `/connect [A] [B]` | Bridge two unrelated domains |
| `lint the wiki` | Health check — orphans, gaps, stale pages |

## Trust boundaries

- `.raw/` is **immutable**. Never edit files under `.raw/` after first write.
- `.claude/skills/` and `.claude/commands/` are checked into git but are *copies* of upstream repos (claude-obsidian + obsidian-second-brain). When we patch them, document the patch in the commit message. Use `bin/resync-claude-obsidian.sh` to pull upstream and re-apply patches.
- `wiki/` is where all compilation happens. Everything here is rewriteable.

## When you're stuck

- Thin retrieval results? Check `qmd status`, make sure `qmd embed` has run after the most recent ingest.
- Pages aren't showing up in `/query`? They may have been written under `.raw/` (not indexed) or under a hidden folder. qmd's collection is `wiki/` only.
- Hooks not firing? Check `.claude/settings.json` in the vault. The plugin-STDOUT bug (`anthropics/claude-code#10875`) only affects hooks distributed via `.claude-plugin/` — our hooks are vault-scoped, so they're fine.
