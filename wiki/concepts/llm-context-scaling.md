---
type: concept
title: "LLM context scaling"
aliases:
  - "long context"
  - "100M token context"
  - "context window scaling"
  - "KV cache compression"
created: 2026-04-11
updated: 2026-04-11
tags:
  - llm-context-scaling
  - long-context
  - kv-cache-compression
  - inference-optimization
  - research
status: developing
complexity: advanced
domain: ai-development
related:
  - "[[agent-memory]]"
  - "[[msa-memory-sparse-attention]]"
  - "[[turboquant]]"
sources:
  - "[[.raw/notion/2026-03-27.md]]"
  - "[[.raw/notion/2026-03-28.md]]"
  - "[[.raw/notion/2026-04-11.md]]"
---

# LLM context scaling

The **active research frontier** as of Q2 2026 is extending practical LLM context length far beyond current norms while keeping serving economics viable. Two sub-threads dominate the briefings: **architecture** (MSA, Document-wise RoPE) and **KV cache compression** (TurboQuant, Flash Attention 4).

## The headline result: MSA and 100M-token context

**MSA: Memory Sparse Attention for Efficient End-to-End Memory Model Scaling to 100M Tokens** — https://arxiv.org/abs/2603.23516

From **EverMind**. First surfaced in the [[.raw/notion/2026-03-27.md|2026-03-27 briefing]] and was the top-trending HuggingFace paper at 2.24k↑, then 2.27k↑ by 2026-03-28 — sustained traction, not a one-day spike.

Key architectural contributions:

1. **Differentiable content-based sparsification.** A "Routing" module dynamically selects relevant memory subsets rather than attending over everything.
2. **Document-wise RoPE.** Positional encoding scheme designed for extreme context extrapolation — the model stays coherent at lengths far beyond its training distribution.
3. **KV Cache Compression with Memory Parallelism.** The cache itself is compressed; multiple memory shards run in parallel so the wall-clock cost of the extra length stays manageable.

The headline number: **performance degrades less than 9% when scaling from 16K to 100M tokens** on long-context QA and Needle-In-A-Haystack benchmarks. For a problem that has been a major open question in the field for the last two years, sub-9% degradation at ~6000× context length is a step-change result.

The **2026-03-27 Signal** called this out explicitly: *"100M-token context is now an active research frontier. Combined with TurboQuant and ongoing KV cache compression work, the practical ceiling for context length is being pushed aggressively from multiple directions simultaneously."*

## The inference-side story: TurboQuant and KV cache compression

**Google TurboQuant** — https://hackaday.com/2026/04/09/turboquant-reducing-llm-memory-usage-with-vector-quantization/ — 2026-04-11 briefing.

Training-free vector-quantization approach to KV cache compression:

- **6× KV cache shrinkage** with claimed zero quality loss
- **8× faster attention** on H100
- **Training-free** — no fine-tuning or distillation required, just a post-hoc compression of the cache

The community adoption speed, per the 2026-03-28 briefing, is the story: **paper → llama.cpp patch → MLX Metal kernels → MacBook Air M4 demo in under a week**. Three separate r/LocalLLaMA threads on 2026-03-28 (867↑, 215↑, 104↑) tracked this. A MacBook Air (M4, 16GB) ran Qwen 3.5-9B with 20K context using the TurboQuant patch. A separate MLX implementation achieved 4.6× KV cache compression with custom Metal kernels at 98% of FP16 speed on Qwen2.5-32B.

Notable: this is arguably the **fastest paper-to-production pipeline** tracked in the briefings. The community crowdsourced implementation across inference stacks before any official tooling.

## Compute-side context

- **Flash Attention 4** (referenced 2026-04-11) claims 1,605 TFLOPs/s on Blackwell. The 2026-04-11 Signal framed this as "KV cache compression is the next inference battleground" — serving cost for long-context workloads could move ~5× in a quarter.
- **Anthropic locked 3.5 GW of TPU capacity** with Google + Broadcom through 2027 ([[.raw/notion/2026-04-11.md]]) — explicitly converting revenue into long-horizon compute commitments, consistent with the belief that long-context serving is about to become a primary workload.

## Why this matters for the user's interests

Long context **partially undermines** the [[agent-memory]] thesis. If the context window is effectively unlimited and cheap, why maintain an external memory store? But the opposite framing also works: cheap long context **enables** agents to load more of their persistent memory on each request, which makes external memory stores *more* useful, not less.

The honest answer is probably "both": larger context windows expand the upper bound on what an agent can hold in working memory, while external memory stores address the durability and cross-session compounding problem that bigger windows don't fix. See [[agent-memory]] and [[llm-wiki-pattern]] for the companion narratives.

## Key numbers to remember

| Result | Source | Date |
|---|---|---|
| <9% degradation from 16K → 100M tokens | MSA | 2026-03-27 |
| 6× KV cache compression, zero quality loss | TurboQuant | 2026-04-11 |
| 8× faster attention on H100 | TurboQuant | 2026-04-11 |
| 4.6× KV compression at 98% FP16 speed on Qwen2.5-32B | Community MLX port | 2026-03-28 |
| 1,605 TFLOPs/s on Blackwell | Flash Attention 4 | 2026-04-11 |
| 1.1M tokens/s serving Qwen3.5-27B on B200s | r/LocalLLaMA | 2026-03-27 |
| Qwen3.5-122B at 198 tok/s on 2× RTX PRO 6000 Blackwell | r/LocalLLaMA | 2026-04-10 |

## Key queries this concept should answer

- "LLM context window scaling"
- "how far has long context come in 2026"
- "what is MSA Memory Sparse Attention"
- "100M token context"
- "KV cache compression TurboQuant"
- "why is context getting cheaper"
