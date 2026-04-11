# compiled-knowledge-base — operating manual

This is a **personal LLM Wiki** for mk, built on claude-obsidian skills, a handful of thinking tools from obsidian-second-brain, and `qmd` hybrid search. It is both an Obsidian vault and a Claude Code project. Read `CRITICAL_FACTS.md` for the ~120-token identity block that is always in context.

## Who you're working with

- mk is a **PhD candidate in computational social science**. Frame technical explanations in terms of research infrastructure, methods, and reproducibility where relevant — not just plain software engineering.
- Primary topic interests: **agent memory**, **LLM context scaling**, **MCP server development**, **AI coding agents** (including critical perspectives), computational social science methods.
- mk reads a **daily AI/ML dev briefing in Notion** every day. Ingesting those briefings into this vault is the primary workflow.
- The vault is used from **both** Claude Code and Obsidian.app — don't break Obsidian-specific files (`.obsidian/`, `_templates/`, wikilink syntax, flat YAML frontmatter).

## Vault structure

```
.raw/               immutable source material (never modify after save)
  notion/           daily briefings pulled from Notion
  articles/         fetched blog posts / web pages
  images/           image sources with OCR descriptions
  transcripts/      audio / YouTube transcripts
.claude/
  skills/           wiki, wiki-ingest, wiki-query, wiki-lint, save, autoresearch, ...
  commands/         /wiki /save /ingest-notion-briefing /challenge /synthesize /emerge /graduate /connect ...
  settings.json     qmd MCP server + hooks
wiki/               the knowledge base — Claude-written, rewriteable
  hot.md            ~500-token hot cache, read first in every session
  index.md          master navigation
  log.md            append-only operation log (newest first)
  concepts/         ideas, frameworks, synthesis pages
  entities/         people, orgs, products, repositories
  sources/          one page per ingested source
  questions/        filed answers from /query
  daily/            per-day briefing summaries (one page per ingested day)
  meta/             vault meta (tag registry, schema notes)
_templates/         concept, entity, source, question, comparison
hooks/              hook shell command sources
bin/                resync + maintenance scripts
CRITICAL_FACTS.md   always-loaded identity block (~120 tokens)
CLAUDE.md           this file
```

## Core principle: compilation over retrieval

When a new source comes in, **rewrite existing pages** to incorporate it. Do not just append a new page. A vault that only grows is a dumping ground; a vault that gets smarter with every ingest is a second brain. `wiki-ingest` enforces this — read its SKILL.md before ingesting anything substantial.

The two-output rule: every answer also updates the vault. If you learned something in the current conversation worth remembering, file it (`/save` or write a wiki page directly).

## Retrieval protocol

Use `wiki-query` for all non-trivial questions about the vault. It already knows how to try qmd first and fall back to plain file reads. **Do not** reach for `Grep` on `wiki/**` directly unless qmd is unavailable AND `wiki-query` is unavailable.

For direct qmd calls when you're scripting:

```bash
qmd query "<natural-language question>" -c kb --json -n 15
qmd get "#<docid>" --full
```

Or via the MCP server — tools `mcp__qmd__query`, `mcp__qmd__get`, `mcp__qmd__multi_get`, `mcp__qmd__status`.

## Hot cache protocol

- `wiki/hot.md` is loaded automatically at session start (SessionStart hook in `.claude/settings.json` runs `cat wiki/hot.md`).
- After compaction, a PostCompact prompt hook tells you to re-read it.
- At the end of a response that touched `wiki/`, a Stop hook prints `WIKI_CHANGED: ...` — when you see that, **rewrite `wiki/hot.md` completely** with the format: `Last Updated`, `Key Recent Facts`, `Recent Changes`, `Active Threads`. Overwrite, don't append. Keep under 500 words.
- Hot cache is a **cache**, not a journal. The journal is `wiki/log.md`.

## Auto-commit protocol

A PostToolUse hook runs `git add wiki/ .raw/` + `git commit` after every `Write` or `Edit`. You don't need to commit manually for ingests. The message format is `wiki: auto-commit YYYY-MM-DD HH:MM`.

For structural or multi-file changes (new skills, patches to this file, schema changes), commit manually with a real message.

## Notion briefing protocol

The daily AI dev briefing in Notion is organised as:
`Daily ai dev briefing` (parent `318a6df2-0ce4-80bf-ac67-e2a622e47636`) → month pages → day pages titled `YYYY-MM-DD`.

To ingest a day:
```
/ingest-notion-briefing 2026-04-11
```
or just `/ingest-notion-briefing` for today.

The command fetches via the already-connected Notion MCP, writes `.raw/notion/YYYY-MM-DD.md`, then delegates to `wiki-ingest`. Every resulting page gets `ingested_via: notion_briefing` and `briefing_date: YYYY-MM-DD` in its frontmatter. This is what makes temporal queries like "what did I learn on 2026-03-28" and retrospective queries like "critical takes on AI coding agents from recent briefings" actually work.

## Frontmatter schema

See `.claude/skills/wiki/references/frontmatter.md` for the full schema. Key additions for this vault (over the claude-obsidian default):

- `sentiment` — `critical | skeptical | neutral | mixed | enthusiastic`. Set it whenever a source takes a clear stance. Retrieval queries for "critical takes on X" rely on BM25 matching `critical` inside frontmatter text.
- `ingested_via` — `notion_briefing | manual | web_fetch | youtube_mcp`.
- `briefing_date` — the originating briefing day, if applicable.

Omit optional fields rather than leaving them blank. `sentiment: ""` is worse than no `sentiment` key.

## Commands cheatsheet

| Command | What it does |
|---|---|
| `/wiki` | Scaffold / route to sub-skills |
| `/ingest-notion-briefing [YYYY-MM-DD]` | Fetch Notion briefing and compile (custom to this vault) |
| `ingest <file-or-url>` | Generic ingest via `wiki-ingest` |
| `query: <question>` | Retrieval via `wiki-query` (qmd-first) |
| `/save` | File current conversation as a wiki note |
| `/autoresearch <topic>` | Autonomous search → fetch → synthesize → file |
| `/canvas` | Visual layer on top of the wiki |
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
