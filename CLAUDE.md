# pkb-mcp — development rules

Installable personal knowledge base MCP server. See @README.md for architecture.

## Vision

pkb is a personal knowledge base for individuals who learn across many domains. You encounter valuable insights in LLM conversations, articles, videos, and books — pkb gives you one place to store them, find them later, and build connections between them over time.

The system handles what's hard to do manually at scale: tagging, linking related pages, embedding for search, and synthesizing multiple sources into coherent wiki pages. The human decides what's worth adding and when to synthesize — the system never adds or rewrites content without being asked.

Each wiki page should be worth reading on its own. Features that help the user consolidate, connect, and improve what's already in the wiki are more valuable than features that add more content automatically.

## Repo structure

This is the **software repo**, not a vault. Personal wiki content lives in a separate vault directory.

- `pkb/` — Python package (server, indexer, search, models, schema)
- `pkb/templates/` — vault scaffolding, copied by `pkb init`
- `tests/` — test suite (242 tests, sandbox-based)
- `tests/fixtures/sample_vault/` — sample vault with 17 pages (test fixture + demo)
- `scripts/` — migration and utility scripts

## Key concepts

- **Vault**: a directory with `wiki/`, `.raw/`, `pkb.db`, and config files. Created by `pkb init`.
- **Origin**: provenance of a page — `webpage | paper | conversation | note | book | transcript | meta`. NOT structural role.
- **Structural role is emergent**: synthesis candidates detected by graph structure (outgoing source edges + `## Synthesis` section), not by declared origin.
- **Edge types**: `source`, `related`, `link` (all singular).
- **Flat vault**: all pages at `wiki/` root, no subdirectories. Node IDs are flat slugs (`agent-memory`).
- **Wikilinks are pathless**: `[[agent-memory]]` not `[[concepts/agent-memory]]`.

## Frontmatter schema

```yaml
title: "Page title"
origin: note
status: developing
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

- `sources:` — graph edges to other wiki pages (used by explore/synthesis detection)
- `raw_sources:` — provenance pointers to `.raw/` files (NOT graph edges)
- `aliases:` — stored in frontmatter so they survive `pkb rebuild --force`
- Omit optional fields rather than leaving them blank.

## CLI

```bash
pkb init ~/my-vault                              # scaffold a new vault
pkb --vault ~/my-vault rebuild [--force]          # rebuild index
pkb --vault ~/my-vault status                     # check health
pkb --vault ~/my-vault search "query"             # test search
pkb --vault ~/my-vault server                     # start MCP server (stdio)
pkb --vault ~/my-vault server --transport http     # HTTP transport
```

Vault discovery: `--vault` CLI arg > `PKB_VAULT_ROOT` env var > current directory.

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
python -m pytest tests/ -v                     # full suite (242 tests)
python -m pytest tests/test_mcp_comprehensive.py -v  # MCP tools + HTTP + auth
```

Tests use `tests/fixtures/sample_vault/` as source data. The sample vault needs a built index — run `pkb --vault tests/fixtures/sample_vault rebuild --force` if search/synthesis tests fail.

## Troubleshooting

- Search tests fail with embedding errors → set `VOYAGE_API_KEY` and rebuild sample vault index
- `pkb` command not found → `pip install -e .`
- Import errors → make sure you're in the venv: `source .venv/bin/activate`
