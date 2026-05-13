# pkb-mcp

A personal wiki that builds itself through conversation. Exposed as an MCP server.

```
You:    "kb: what do I know about agent memory?"

pkb:    Found 5 pages on agent memory. Your main page links to 3 sources.
        Here's a summary. Want me to pull the full page?

You:    "Add the key insight from this conversation to my KB"

pkb:    Here's what I'd save:
        Title: "Agent memory — retrieval patterns"
        Tags: [agent-memory, rag, retrieval]
        Related: [[agent-memory]], [[vector-databases]]

        Look good?

You:    "Yes"

pkb:    Saved. Also found 2 similar pages you might want to link.
```

No batch pipelines. No manual wiki editing. Your knowledge compounds through conversation.

## What makes this different

Every tool in this space makes you choose:

**Vector databases** (Pinecone, ChromaDB, Mem.ai) give you search. Ask about agent memory after ingesting 50 papers and you get 50 ranked chunks. Every time. The synthesis happens in the LLM's context window, inconsistently, and nothing is retained.

**Wiki compilers** (obsidian-second-brain, Khoj) give you pages. But they compile eagerly — every new source triggers updates to all related pages. That's O(n) LLM calls per ingest, where n is your corpus size. Works at 20 pages. Breaks at 2,000.

**pkb gives you both.** Every source is searchable immediately via hybrid retrieval (FTS5 + vector + RRF). Pages are updated on demand — only when you decide to revise them. The human stays in the loop: the LLM drafts, you approve.

Pages are just pages. No prescribed sections, no compilation rituals. The structure is whatever you give it. Connections between pages are tracked as graph edges, and the system suggests links when you add new content — but you decide what to connect.

Built on SQLite + FTS5 + sqlite-vec + Voyage embeddings + FastMCP. Single-file database. Zero ops. Runs locally. Also an [Obsidian](https://obsidian.md) vault — browse your wiki with wikilinks and backlinks.

## Architecture

```
                    wiki/*.md  <-- THE PRODUCT
                    Pages with frontmatter, wikilinks,
                    and graph edges
                         ^ write               | read (index)
                         |                     v
+--------------+     +-------------------------------------------+
| Claude.ai    |     |  pkb MCP Server (FastMCP)                 |
| Claude Code  |---->|                                           |
| Cursor       |     |  3 tools: find, save, status              |
| Any MCP client|     |                                           |
+--------------+     |  +-------------------------------------+  |
                     |  | SQLite + FTS5 + sqlite-vec          |  |
                     |  | - BM25 keyword search               |  |
                     |  | - Vector similarity (Voyage 3.5)    |  |
                     |  | - Reciprocal Rank Fusion            |  |
                     |  | - DAG edges + graph traversal       |  |
                     |  +-------------------------------------+  |
                     +-------------------------------------------+
```

The wiki pages are the product. Everything else is infrastructure to build and search them. Markdown files are the source of truth — delete the SQLite index and rebuild from markdown in seconds.

## Quick start

### Install

```bash
pip install pkb-mcp
```

Or from source:

```bash
git clone https://github.com/Miandari/personal-knowledge-base-mcp
cd personal-knowledge-base-mcp
pip install -e .
```

Requires Python 3.11+ and a [Voyage AI](https://www.voyageai.com/) API key (free tier: 200M tokens/month).

### Create a vault

```bash
pkb init ~/my-knowledge-base
cd ~/my-knowledge-base
cp .env.example .env
# Edit .env — set your VOYAGE_API_KEY
pkb rebuild
```

`pkb init` scaffolds everything: wiki directory, Obsidian config, Claude Code skills, auto-commit hooks, and a starter index page. If you skip this step and try to use the MCP tools, they'll return clear setup instructions.

### Connect an LLM client

**Claude Desktop** (stdio — recommended):

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pkb": {
      "command": "/path/to/.venv/bin/pkb",
      "args": ["--vault", "/Users/you/my-knowledge-base", "server"],
      "env": {
        "VOYAGE_API_KEY": "your-key-here"
      }
    }
  }
}
```

The client manages the server lifecycle — no terminal to babysit.

**Claude Code** (auto-configured by `pkb init`):

```bash
cd ~/my-knowledge-base
claude
```

The vault's `.claude/settings.json` already configures the MCP server.

**Cursor / HTTP clients** (Streamable HTTP — for remote access or multi-client):

```bash
pkb --vault ~/my-knowledge-base server --transport http --port 8181
```

```json
{
  "mcpServers": {
    "pkb": { "url": "http://127.0.0.1:8181/mcp" }
  }
}
```

Set `KB_MCP_TOKEN` for auth when exposing over a network. Use `--no-auth` to disable for local testing.

### Try it

```
"kb: what do I know about agent memory?"
"Search my KB for critical takes on AI coding"
"What's in my notes about MCP?"
```

The `kb:` prefix or phrases like "my KB", "my notes", "my wiki" signal the LLM to use pkb instead of web search.

## Adding knowledge

Knowledge enters from anywhere — articles, papers, YouTube transcripts, or conversations with LLMs.

**From a conversation:** You're chatting with Claude about a paper. You say "add the key insights about RAPTOR to my KB." The LLM drafts a wiki page with title, body, tags, and related links, shows you for approval, then calls `kb_save`. The system returns `suggested_related` — existing pages that are semantically similar — and `suggested_tags` from those pages, so the LLM can offer to link and tag them.

**From a URL:** "Add this article to my KB: https://..." — the LLM fetches, summarizes, and calls `kb_save`.

**From Claude Code:** The `wiki-ingest` skill handles raw file acquisition (URLs, YouTube, audio, images, PDFs) and writes structured pages via `kb_save`.

## MCP tools

Three tools. That's the entire surface.

| Tool | Purpose |
|---|---|
| `kb_find` | Search (query), get page (id), or browse (filters). Hybrid FTS5 + vector search with RRF. |
| `kb_save` | Create, update section, update metadata, or reindex. Auto-reindexes after every write. Returns `suggested_related` and `suggested_tags` on create. |
| `kb_status` | Index health: node count, edge count, embedding coverage, stale count |

`kb_find` has three modes depending on which parameters you pass:

```
kb_find(query="agent memory")     # search — ranked results
kb_find(id="agent-memory")        # get — full page + edges
kb_find(origin="paper")           # browse — filtered listing
```

`kb_save` has five modes:

```
kb_save(title="...", origin="note", body="...")           # create
kb_save(id="...", section="Summary", body="new content")  # update section
kb_save(id="...", body="full new body")                    # replace body
kb_save(id="...", tags=["a", "b"], related=["page-id"])   # update metadata (replace semantics)
kb_save(id="...")                                          # reindex after external edit
```

## Data model

Every page is a **node** with an `origin` field describing its provenance (`webpage`, `paper`, `conversation`, `note`, `book`, `transcript`, `meta`). Nodes link via **edges** with three types:

- **source** — "this page was built from these" (frontmatter `sources: []`)
- **related** — "this page is related to these" (frontmatter `related: []`)
- **link** — "this page mentions that page" (extracted from `[[inline wikilinks]]`)

No fixed layers. Depth is emergent. Structural role (hub, leaf, source authority) is computed from graph structure at query time — never stored or declared.

## Design philosophy

**The wiki is the product.** Search and graph traversal exist to help you find and connect pages.

**Pages are just pages.** No prescribed sections. No compilation rituals. Pages have whatever structure you give them. All modifications are human-in-the-loop.

**Curated, not exhaustive.** You decide what enters. High signal, tractable knowledge.

**Markdown is source of truth.** SQLite is derived. Edit in any text editor, `pkb rebuild` to sync. The wiki is also a valid Obsidian vault — open it in Obsidian.app for wikilink navigation and backlinks.

**MCP-native.** Not locked to one client. Works with Claude.ai, Claude Code, Claude Desktop, Cursor, or anything that speaks MCP.

**Vault and package are separate.** Install pkb once, create as many vaults as you want. Each vault is a self-contained directory with markdown files, an Obsidian config, and a SQLite index. No code lives in the vault.

## CLI

```bash
pkb init ~/my-vault                        # scaffold a new vault
pkb --vault ~/my-vault rebuild [--force]   # rebuild index
pkb --vault ~/my-vault status              # check health
pkb --vault ~/my-vault search "query"      # test search
pkb --vault ~/my-vault server              # start MCP server (stdio)
```

Vault discovery: `--vault` CLI arg > `PKB_VAULT_ROOT` env var > current directory.

## Testing

```bash
pip install -e ".[test]"
python -m pytest tests/ -v
```

216 tests covering the indexer, search (FTS5 + hybrid), graph traversal, all 3 MCP tools, HTTP transport, auth middleware, end-to-end workflows, frontmatter schema validation, and LLM-judge synthesis quality. Tests use a sample vault (`tests/fixtures/sample_vault/`) as the source fixture.

## Tech stack

- **Python 3.11+**
- **SQLite** with FTS5 (BM25 search) and sqlite-vec (vector search)
- **Voyage AI** embeddings (voyage-3.5, 1024 dimensions)
- **FastMCP** (MCP server framework)
- **apsw** (SQLite bindings with extension loading — required for sqlite-vec on macOS)
- **Pydantic** (data models)

## Prior art

This project builds on ideas from:

- [Andrej Karpathy's LLM wiki pattern](https://x.com/karpathy/status/1913669663498432937) — the idea that agents should maintain persistent, compounding knowledge bases
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) — Claude + Obsidian skills framework (used as the base layer)
- [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) — thinking tools for Obsidian (cherry-picked commands)

## License

MIT
