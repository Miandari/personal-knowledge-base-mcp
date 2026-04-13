---
type: entity
title: "GraphRAG"
created: 2026-04-13
updated: 2026-04-13
status: seed
tags:
  - graphrag
  - knowledge-graph
  - rag
  - prior-art
  - microsoft-research
url: "https://arxiv.org/abs/2404.16130"
sentiment: neutral
ingested_via: conversation
related: []
---

# GraphRAG

**Source**: Microsoft Research (Edge et al., 2024)
**Paper**: [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)
**GitHub**: [microsoft/graphrag](https://github.com/microsoft/graphrag)

Microsoft's approach to retrieval-augmented generation that layers a knowledge graph on top of vector retrieval. Key innovation: LLM-extracted entity-relationship graphs with hierarchical community detection and pre-generated community summaries.

## How it works

1. **Text chunking** — split documents into analyzable units
2. **Entity + relationship extraction** — LLM extracts entities and relationships from each chunk
3. **Knowledge graph construction** — entities are nodes, relationships are edges
4. **Community detection** — Leiden algorithm groups related entities into hierarchical communities
5. **Community summarization** — LLM generates natural language summaries at each community level
6. **Multi-resolution retrieval** — Local Search (fan out from specific entities), Global Search (traverse community summaries), DRIFT Search (combine both)

## Relevance to pkb

GraphRAG solves the "global question" problem that naive vector RAG fails on (e.g., "what are the main themes in this dataset?"). Community summaries provide pre-computed answers at different levels of abstraction — similar to what pkb's synthesis pages provide.

## Why pkb doesn't use GraphRAG

GraphRAG is **batch-indexed and read-only**. The entire graph + community structure must be rebuilt when the corpus changes. Indexing is expensive (the docs warn about this explicitly). For a personal KB where new sources arrive daily and synthesis must update incrementally, this is a dealbreaker. pkb solves the same multi-resolution problem with demand-driven compilation instead of pre-computed community hierarchies.

## Key takeaway

GraphRAG's multi-resolution retrieval (local entities → community summaries → global themes) is the right *query* structure. But its batch *indexing* approach doesn't fit an incremental, write-heavy personal KB. pkb gets equivalent multi-resolution behavior through the DAG: leaf nodes are local, synthesis pages are community-level, and deeper syntheses are global — all updated incrementally on demand.