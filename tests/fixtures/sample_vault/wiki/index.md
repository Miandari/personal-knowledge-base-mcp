---
title: Wiki index
origin: meta
status: developing
tags:
  - meta
created_at: 2026-04-11
updated_at: 2026-04-11
---

# Wiki index

Master navigation for the compiled-knowledge-base vault. Scan section headers first to decide which sections to read — do not read the whole index unless you need to.

## Concepts

- [[ai-coding-agents]] — LLM-driven tools that edit code (Claude Code, Cursor, Devin, Copilot, Windsurf, OpenClaw/Hermes harnesses). Capabilities, production limits, and the advisor + harness + skills architectural pattern.
- [[llm-wiki-pattern]] — compilation over retrieval. Karpathy's idea that agents should maintain persistent, compounding, human-readable knowledge bases. Five independent implementations observed in Q2 2026.
- [[agent-memory]] — the dominant agent-tooling theme of Q2 2026. External, mutable, agent-owned knowledge stores (mempalace, MemMA, Memento-Skills, LLM wikis). Replacing / augmenting ever-larger context windows.
- [[llm-context-scaling]] — MSA 100M-token attention, TurboQuant KV cache compression, Flash Attention 4. The other side of the agent-memory story: if context gets cheap, external memory changes shape.
- [[mcp-ecosystem]] — MCP at 97M monthly SDK downloads. Official servers from Google (GA, Colab) and WordPress. 2026 roadmap: Streamable HTTP, Tasks primitive, enterprise SSO/audit.

## Entities

- [[claude-code]] — Anthropic's CLI coding agent. Used daily by mk. Recent releases, known issues, ecosystem.
- [[claude-obsidian]] — the LLM-wiki plugin this vault is built on (AgriciDaniel/claude-obsidian, 490★+)
- [[obra-superpowers]] — composable SKILL.md framework, #1 trending GitHub repo on 2026-03-28 (120k★)
- [[mempalace]] — ChromaDB-based memory system, ~41k★, 5,871 stars/day on 2026-04-11

## Sources

- [[uncomfortable-truths-ai-coding-agents]] — **critical** red-team take on AI coding agents in production (sarah_builds, 2026-03-26, HN 75pts). The canonical citation for the production-readiness objection.

## Daily

- (none yet — daily briefing summaries go here)

## Questions

- (none yet — filed answers from `/query` go here)

## Coverage map

| Topic | Status | Canonical page |
|---|---|---|
| AI coding agents — overview | developing | [[ai-coding-agents]] |
| AI coding agents — critical view | developing | [[uncomfortable-truths-ai-coding-agents]] |
| LLM wiki / compilation-over-retrieval | developing | [[llm-wiki-pattern]] |
| Agent memory infrastructure | developing | [[agent-memory]] |
| Long context + KV cache | developing | [[llm-context-scaling]] |
| MCP | developing | [[mcp-ecosystem]] |
| Claude Code | developing | [[claude-code]] |

## Tag registry (in use)

- `ai-coding-agents`, `critique`, `production-readiness`, `llm-limitations`, `software-engineering`
- `llm-wiki-pattern`, `agent-memory`, `knowledge-management`, `compilation-over-retrieval`
- `llm-context-scaling`, `long-context`, `kv-cache-compression`, `inference-optimization`
- `mcp`, `mcp-server-development`, `agent-tooling`, `protocol`
- `claude-code`, `anthropic`, `tool`
- `github-repository`, `chromadb`, `skills-framework`
- `research`, `meta`
