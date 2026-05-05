---
title: RAPTOR
origin: conversation
status: seed
ingested_via: manual
aliases:
  - "entities/raptor"
tags:
  - raptor
  - hierarchical-retrieval
  - rag
  - prior-art
  - stanford
related: []
sources: []
sentiment: neutral
url: "https://arxiv.org/abs/2401.18059"
created_at: 2026-04-13
updated_at: 2026-04-13
---

# RAPTOR

**Source**: Stanford (Sarthi et al., 2024)
**Paper**: [RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval](https://arxiv.org/abs/2401.18059)
**GitHub**: [parthsarthi03/raptor](https://github.com/parthsarthi03/raptor)
**Venue**: ICLR 2024

Recursive Abstractive Processing for Tree-Organized Retrieval. Builds a tree of increasingly abstract summaries from bottom up, enabling retrieval at different levels of abstraction.

## How it works

1. **Chunk** documents into ~100 token excerpts
2. **Embed** chunks using SBERT
3. **Cluster** embeddings using Gaussian Mixture Models (soft clustering — a chunk can belong to multiple clusters)
4. **Summarize** each cluster using GPT-3.5-turbo
5. **Repeat** — embed the summaries, cluster them, summarize the clusters — building a tree from bottom up
6. **Retrieve** at query time using either tree traversal (top-down, selecting best nodes at each level) or collapsed tree (flatten all levels, retrieve by cosine similarity across all)

The collapsed tree approach treats all nodes — raw chunks and summaries at every level — as a flat set for retrieval. This lets a single query surface both fine-grained details (from leaf chunks) and high-level themes (from root summaries).

## Results

Coupled with GPT-4, RAPTOR improved the best performance on the QuALITY benchmark by 20% in absolute accuracy. The key finding: retrieval with recursive summaries significantly outperforms traditional chunk-level retrieval on multi-step reasoning questions.

## Relevance to pkb

RAPTOR is the closest prior art to pkb's multi-resolution approach. Both systems have raw sources at the bottom and increasingly abstract summaries above. The crucial difference: RAPTOR builds the tree as a batch process — the entire tree is reconstructed from scratch when the corpus changes. The 72% compression rate at each level means the tree is efficient, but it's still a static index.

pkb achieves equivalent multi-resolution structure through an emergent DAG where synthesis pages are created on demand. A synthesis page that covers 5 sources is roughly equivalent to a RAPTOR cluster summary one level up. A synthesis that synthesizes 3 other syntheses is two levels up. The depth emerges from user exploration patterns rather than automated clustering.

## Key difference from pkb

RAPTOR's clustering is automated (GMM) and comprehensive (every chunk is clustered). pkb's "clustering" is human-curated and selective — only topics the user explores get synthesis pages. This is a feature, not a limitation: it means the system focuses compilation effort where the user actually needs understanding.