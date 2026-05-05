# pkb-mcp

A personal wiki that builds itself through conversation. Exposed as an MCP server.

```
You:    "kb: what do I know about agent memory?"

pkb:    Found your synthesis page on agent memory (last updated April 11).
        3 new sources arrived since — mempalace repo, a survey paper, and
        your notes from yesterday's conversation.
        Want me to incorporate them?

You:    "Yes"

pkb:    Done. Page rewritten. 3 sources integrated, 1 contradiction flagged.
        Next time you ask, it's fresh.
```

No batch pipelines. No manual wiki editing. Your knowledge compounds through conversation.

## What makes this different

Every tool in this space makes you choose:

**Vector databases** (Pinecone, ChromaDB, Mem.ai) give you search. Ask about agent memory after ingesting 50 papers and you get 50 ranked chunks. Every time. The synthesis happens in the LLM's context window, inconsistently, and nothing is retained.

**Wiki compilers** (obsidian-second-brain, Khoj) give you pages. But they compile eagerly — every new source triggers updates to all related pages. That's O(n) LLM calls per ingest, where n is your corpus size. Works at 20 pages. Breaks at 2,000.

**pkb gives you both.** Every source is searchable immediately via hybrid retrieval (FTS5 + vector + RRF). Wiki pages are compiled on demand — only when you explore a topic and decide the scattered sources should be unified. Compilation is a side effect of exploration, not a batch job.

The knowledge structure is a DAG where depth emerges naturally: a page synthesizing 5 sources is depth 1, a page synthesizing 3 synthesis pages is depth 2. No fixed layers. The things you never ask about stay as searchable raw sources — and that's fine.

Built on SQLite + FTS5 + sqlite-vec + Voyage embeddings + FastMCP. Single-file database. Zero ops. Runs locally. Also an [Obsidian](https://obsidian.md) vault — browse your wiki with wikilinks and backlinks.

## Architecture

```
                    wiki/*.md  <-- THE PRODUCT
                    Living synthesis pages with frontmatter,
                    wikilinks, and DAG structure
                         ^ write (compile)     | read (index)
                         |                     v
+--------------+     +-------------------------------------------+
| Claude.ai    |     |  pkb MCP Server (FastMCP)                 |
| Claude Code  |---->|                                           |
| Cursor       |     |  8 tools: search, explore, get, list,     |
| Any MCP client|     |           add, synthesize, reindex,       |
+--------------+     |           status                          |
                     |                                           |
                     |  +-------------------------------------+  |
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

**From a conversation:** You're chatting with Claude about a paper. You say "add the key insights about RAPTOR to my KB." The LLM calls `kb_add`, writes a wiki page with frontmatter and tags, embeds it, and it's immediately searchable. When adding, the system returns `suggested_related` — existing pages that are semantically similar — so the LLM can offer to link them.

**From a URL:** "Add this article to my KB: https://..." — the LLM fetches, summarizes, and calls `kb_add`.

**From Claude Code:** The `wiki-ingest` skill handles raw file acquisition (URLs, YouTube, audio, images, PDFs) and writes structured pages via `kb_add`.

Nothing is compiled automatically. Sources sit as searchable leaf nodes until you explore a topic and decide to synthesize them.

## The explore → compile loop

1. You ask about a topic → LLM calls `kb_explore("agent memory")`
2. System returns the synthesis page (if one exists), whether it's stale, new sources not yet incorporated, adjacent topics, and suggested actions
3. LLM presents this conversationally: *"Your agent memory page was last updated April 11. Three new sources arrived since. Want me to incorporate them?"*
4. You say yes → LLM calls `kb_synthesize`, gets back a structured prompt with the synthesis section + source pages + rewrite rules + available wikilink slugs, then rewrites the synthesis section
5. LLM saves the file and calls `kb_reindex` → index is immediately up to date
6. Next time you explore, it's fresh

Synthesis detection is graph-based: any page with outgoing source edges or a `## Synthesis` section is a candidate, regardless of its `origin` field. This means a page can organically grow into a synthesis hub without being declared as one upfront.

## MCP tools

| Tool | Purpose |
|---|---|
| `kb_search` | Hybrid FTS5 + vector search with Reciprocal Rank Fusion |
| `kb_explore` | Exploration: synthesis page + staleness + unincorporated sources + adjacent topics |
| `kb_get` | Full page content + metadata + DAG edges |
| `kb_list` | Browse/filter pages by origin, tag, status |
| `kb_add` | Add a new page — writes markdown + indexes + embeds + suggests related pages |
| `kb_synthesize` | Assemble a synthesis prompt — returns context for the `## Synthesis` section only |
| `kb_reindex` | Re-index a single file after edit — must be called after any file write |
| `kb_status` | Index health: node count, edge count, embedding coverage, stale count |

## Data model

Every page is a **node** with an `origin` field describing its provenance (`webpage`, `paper`, `conversation`, `note`, `book`, `transcript`, `meta`). Nodes link via **edges** with three types:

- **source** — "this page was built from these" (frontmatter `sources: []`)
- **related** — "this page is related to these" (frontmatter `related: []`)
- **link** — "this page mentions that page" (extracted from `[[inline wikilinks]]`)

No fixed layers. Depth is emergent. Structural role (synthesis hub, leaf, source authority) is computed from graph structure at query time — never stored or declared.

Staleness is detected two ways: known sources updated after last compile (SQL), and new semantically related pages not yet in the sources list (detected during `kb_explore`). Pages that explicitly declare `related: [[concept-page]]` always surface as unincorporated sources when that concept is explored.

## Design philosophy

**The wiki is the product.** Search, graph traversal, and staleness detection exist to decide which pages to compile next.

**Curated, not exhaustive.** You decide what enters. High signal, tractable synthesis.

**Demand-driven, not push-based.** Push compilation is O(n) per ingest. Pull compilation is O(1) per request. This is the scalability insight.

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

242 tests covering the indexer, search (FTS5 + hybrid), graph traversal, all 8 MCP tools, HTTP transport, auth middleware, end-to-end workflows, frontmatter schema validation, and LLM-judge synthesis quality. Tests use a sample vault (`tests/fixtures/sample_vault/`) as the source fixture.

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
