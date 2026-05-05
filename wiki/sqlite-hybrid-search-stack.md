---
title: SQLite hybrid search stack
origin: conversation
status: seed
ingested_via: manual
aliases:
  - "concepts/sqlite-hybrid-search-stack"
tags:
  - sqlite
  - fts5
  - sqlite-vec
  - hybrid-search
  - rrf
  - pkb-design
related: []
sources: []
sentiment: enthusiastic
created_at: 2026-04-13
updated_at: 2026-04-13
---

# SQLite hybrid search stack

The storage and search architecture chosen for pkb: **SQLite + FTS5 + sqlite-vec**, combining keyword search (BM25), vector similarity search, and structured metadata filtering in a single embedded database file.

## Components

- **SQLite** — embedded relational database, the foundation
- **FTS5** — SQLite's built-in full-text search extension, provides BM25 ranking
- **sqlite-vec** — Alex Garcia's vector search extension for SQLite, provides KNN similarity search
- **Reciprocal Rank Fusion (RRF)** — combines FTS5 and vector results without needing to calibrate incompatible score types

## Why this over alternatives

### vs qmd (what pkb replaced)

qmd provided hybrid search (BM25 + vector + rerank) but as an opaque CLI tool with no metadata filtering, no graph traversal, no write operations, and no way to add custom tools. Replacing it with raw SQLite gave full control over the schema — critical for the DAG model (edges table), staleness detection (date comparisons via SQL), and structured filtering (WHERE clauses on denormalized metadata fields).

### vs LanceDB

LanceDB was the previous project's winner. Strong vector search with good metadata filtering, embedded and serverless. But it has **no built-in BM25/full-text search** — you'd need to bolt that on separately, defeating the single-store advantage. For a KB where frontmatter tags and exact keyword matches are critical (e.g., finding all pages with `sentiment: critical`), missing FTS was a dealbreaker.

### vs ChromaDB

Simple API, good for prototyping. But less efficient than SQLite for larger-than-memory datasets and the ecosystem is less mature for hybrid search patterns.

### vs standalone vector databases (Pinecone, Qdrant, Weaviate)

Overkill for a personal KB of 100–2000 pages. Adds operational complexity (separate server process, network calls) for no benefit at this scale. SQLite is a single file with zero ops.

## The converging pattern

As of 2026, the SQLite + FTS5 + sqlite-vec stack is becoming standard for local-first AI memory. Notable implementations: AIngram (FTS5 + sqlite-vec + knowledge graph + MCP server, 5 days old as of April 2026), BrainDB (4300+ memories, sub-1ms latency), and a hybrid retriever for 16,894 Obsidian files (83MB total footprint, 4-minute full reindex).

## Key design decisions in pkb

- **Chunk-level embeddings**, not page-level. A 3000-word page embeds as multiple ~500-token chunks. Search retrieves the best chunk, returns the parent page.
- **Embedding cache** keyed by (content_hash, model). Unchanged chunks skip the Voyage API call. Model column prevents mixed-model vector space corruption on model upgrades.
- **Pre-filtering in CTEs**. Metadata filters (type, sentiment) are applied inside the FTS and vec CTEs before LIMIT, not after. Prevents recall destruction when the top N results are dominated by one type.
- **UNION-based RRF** instead of FULL OUTER JOIN (which SQLite doesn't support).
- **Raw RRF scores returned**, no normalization to [0,1]. Only relative ordering matters.