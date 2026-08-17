# pkb-mcp — development rules

Installable personal knowledge base MCP server. See @README.md for architecture.

## Vision

pkb is a personal knowledge base for individuals who learn across many domains. You encounter valuable insights in LLM conversations, articles, videos, and books — pkb gives you one place to store them, find them later, and build connections between them over time.

The system handles what's hard to do manually at scale: tagging, linking related pages, embedding for search, and connecting sources. The human decides what's worth adding and how to organize it — the system never adds or rewrites content without being asked.

Each wiki page should be worth reading on its own. Features that help the user consolidate, connect, and improve what's already in the wiki are more valuable than features that add more content automatically.

## Design philosophy: pages are just pages

No prescribed sections. No special synthesis ritual. Pages have whatever structure the user gives them. The LLM reads pages and writes updates through the same tools it uses for everything else. All page modifications are human-in-the-loop.

**System 1 (conversation-time):** Low-latency, focused MCP tools for adding, finding, reading, and updating pages. Three tools: `kb_find`, `kb_save`, `kb_status`.

**System 2 (reflection-time):** Future tools for auditing knowledge shape, finding gaps, detecting contradictions, consolidating pages. Graph traversal and staleness detection functions exist in `search.py` as infrastructure for this.

## Repo structure

This is the **software repo**, not a vault. Personal wiki content lives in a separate vault directory.

- `pkb/` — Python package (server, indexer, search, models, schema)
- `pkb/templates/` — vault scaffolding, copied by `pkb init`
- `tests/` — test suite (212 tests, sandbox-based)
- `tests/fixtures/sample_vault/` — sample vault with 17 pages (test fixture + demo)
- `scripts/` — migration and utility scripts

## Key concepts

- **Vault**: a directory with `wiki/`, `.raw/`, `pkb.db`, and config files. Created by `pkb init`.
- **Origin**: provenance of a page — `webpage | paper | conversation | note | book | transcript | meta`. NOT structural role.
- **Structural role is emergent**: hub pages detected by graph structure (outgoing source edges), not by declared origin or section headings.
- **Edge types**: `source`, `related`, `link` (all singular).
- **Flat vault**: all pages at `wiki/` root, no subdirectories. Node IDs are flat slugs (`agent-memory`).
- **Wikilinks are pathless**: `[[agent-memory]]` not `[[concepts/agent-memory]]`.

## Frontmatter schema

```yaml
title: "Page title"
origin: note
ingested_via: manual
aliases:
  - "Old Name"
tags:
  - topic
related:
  - "[[other-page]]"
sources:
  - "[[wiki-source-page]]"
raw_sources:
  - ".raw/notion/2026-04-10.md"
created_at: 2026-05-05
updated_at: 2026-05-05
```

- `sources:` — graph edges to other wiki pages (used by graph traversal)
- `raw_sources:` — provenance pointers to `.raw/` files (NOT graph edges)
- `aliases:` — stored in frontmatter so they survive `pkb rebuild --force`
- Omit optional fields rather than leaving them blank.

## MCP tools

| Tool | Purpose |
|------|---------|
| `kb_find` | Search (query), get page (id), or browse (filters) |
| `kb_save` | Create, update section, update metadata, or reindex pages |
| `kb_status` | Index health check |

## CLI

```bash
pkb init ~/my-vault [--no-git]                    # scaffold a new vault (git init by default)
pkb --vault ~/my-vault rebuild [--force]          # rebuild index
pkb --vault ~/my-vault status                     # check health (incl. version-control state)
pkb --vault ~/my-vault search "query"             # search
pkb --vault ~/my-vault server                     # start MCP server (stdio)
pkb --vault ~/my-vault server --transport http     # HTTP transport
```

`search` (alias `find`) mirrors the `kb_find` tool exactly — both call `search.find()`,
so neither surface can drift ahead of the other. Omit the query to browse:

```bash
pkb search --tag agent-memory --sort created_at   # browse by filters, no query
pkb search "retrieval" --origin paper --created-after 2026-06
pkb search --id agent-memory                       # one page by id
```

Filters: `--origin --tag --sentiment --created-after/before --published-after/before
--sort --limit --mode`. Dates take `YYYY`, `YYYY-MM`, or `YYYY-MM-DD` and error rather
than being dropped. **Any new retrieval behaviour goes in `search.find()`, not in a
caller** — the CLI fell three features behind the MCP tool precisely because the
dispatch was duplicated.

Vault discovery: `--vault` CLI arg > `PKB_VAULT_ROOT` env var > current directory.
Prefer `--vault` over `cd` in scripts and hooks.

## Vault versioning

`pkb init` runs `git init` plus an initial commit. This is not a nicety: the scaffold
ships two git-dependent hooks (`hooks/hooks.json`) that are guarded by `[ -d .git ]`
and therefore **fail open** — in a non-repo vault they no-op silently and forever.
Shipping the machinery without arming it is how a vault drifts for months with no
record. `pkb status` prints a `Versioned:` line so the unarmed state is visible.

When touching this area, keep three invariants:

- `.gitignore` must exclude `.env` and `pkb.db*`. The glob matters — migration backups
  land as `pkb.db.bak-*` and are multi-megabyte binaries.
- The auto-commit hook must not name a path that may not exist. It previously ran
  `git add wiki/ .raw/`, which exits 128 when `.raw/` is absent, aborting the `&&`
  chain before the commit. Use `git add -A`.
- Version config, not just content. The drift that motivated all of this was in
  `CLAUDE.md`, `_templates/`, and `.claude/skills/` — never in `wiki/`.

## MCP client configuration

```json
{
  "mcpServers": {
    "pkb": {
      "command": "/path/to/.venv/bin/pkb",
      "args": ["--vault", "/path/to/my-vault", "server"],
      "env": {
        "VOYAGE_API_KEY": "your-key-here"
      }
    }
  }
}
```

## Testing

```bash
pip install -e ".[test]"
python -m pytest tests/ -v                     # full suite (212 tests)
python -m pytest tests/test_mcp_comprehensive.py -v  # MCP tools + HTTP + auth
```

Tests use `tests/fixtures/sample_vault/` as source data. The sample vault needs a built index — run `pkb --vault tests/fixtures/sample_vault rebuild --force` if search tests fail.

## Troubleshooting

- Search tests fail with embedding errors → set `VOYAGE_API_KEY` and rebuild sample vault index
- `pkb` command not found → `pip install -e .`
- Import errors → make sure you're in the venv: `source .venv/bin/activate`
