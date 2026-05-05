---
title: Demand-driven compilation
origin: conversation
status: seed
ingested_via: manual
aliases:
  - "concepts/demand-driven-compilation"
tags:
  - architecture
  - compilation
  - scalability
  - pkb-design
related: []
sources: []
sentiment: enthusiastic
created_at: 2026-04-13
updated_at: 2026-04-13
---

# Demand-driven compilation

The core architectural pattern of pkb-mcp: **synthesis pages are compiled when the user explores a topic, not when sources are ingested.**

## The scaling problem with push compilation

Traditional LLM wiki systems (like [[llm-wiki-pattern]] implementations such as obsidian-second-brain) compile eagerly: every ingested source triggers updates to all related wiki pages. This is O(n) LLM calls per ingest, where n grows with the number of existing pages the compiler must read to find what needs updating. At 14 pages this works. At 2000 pages (a year of YouTube transcripts, papers, conversations, briefings), retrieval quality *during compilation* degrades — the compiler can't reliably find the right pages to update, and knowledge silently fails to connect.

## The demand-driven alternative

In pkb, ingestion is cheap: `kb_add` writes a markdown file and indexes it (FTS5 + vector embedding). No compilation happens. The source is immediately searchable but hasn't been synthesized into any concept page.

Compilation is triggered by exploration:

1. User asks "what do I know about agent memory?"
2. `kb_explore` returns: synthesis page (if exists), staleness indicators, unincorporated sources, adjacent topics
3. If stale or new sources exist, the system offers to compile
4. User says yes → `kb_synthesize` assembles a prompt with the existing page + source pages → the LLM rewrites the page → `kb_reindex` updates the index

This is O(1) per user request regardless of corpus size. The LLM only reads the pages relevant to *this specific topic*, not the entire vault.

## The materialized view analogy

The relationship between raw sources and synthesis pages is analogous to materialized views in databases. Raw sources are base tables. Synthesis pages are materialized views — precomputed joins across sources. You don't materialize every possible view eagerly. You materialize the ones that get queried, and refresh them when the underlying data changes.

## Key insight: exploration generates compilation signals

The interaction history is itself a data source. Every time a user drills down into a topic, they're telling the system which syntheses are worth maintaining. Topics you never ask about stay as raw sources — and that's fine, they're still searchable. The system learns what to compile from your actual information needs.

## Prior art

- **[[graphrag]]** — Microsoft's hierarchical knowledge graph + community summaries. Has multi-resolution structure but is batch-indexed and read-only — rebuilds the entire graph when corpus changes. No incremental updates.
- **[[raptor]]** — Stanford's recursive abstractive tree. Clusters and summarizes chunks bottom-up. Also batch-only — rebuilds the entire tree from scratch on corpus change.
- **Google ADK MemoryService** — distinguishes "reactive recall" (agent searches on demand) from "proactive recall" (system pre-fetches). Close to our pattern but treats retrieval as a function call, not a dialogue.

Neither GraphRAG nor RAPTOR supports the incremental, write-heavy use case of a personal KB where new sources arrive daily and synthesis must update without reprocessing everything.