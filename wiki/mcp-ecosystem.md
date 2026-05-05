---
title: MCP ecosystem
origin: note
status: developing
aliases:
  - "Model Context Protocol"
  - "MCP server development"
  - "concepts/mcp-ecosystem"
tags:
  - mcp
  - mcp-server-development
  - agent-tooling
  - protocol
related:
  - "[[ai-coding-agents]]"
  - "[[claude-code]]"
  - "[[agent-memory]]"
sources: []
raw_sources:
  - ".raw/notion/2026-03-27.md"
  - ".raw/notion/2026-03-28.md"
  - ".raw/notion/2026-04-11.md"
complexity: intermediate
domain: ai-development
created_at: 2026-04-11
updated_at: 2026-04-11
---

# MCP ecosystem

**MCP (Model Context Protocol)** is now the de-facto standard protocol for connecting LLM agents to external tools, data sources, and memory. The 2026-03-28 briefing documented the headline number: **MCP crossed 97M monthly SDK downloads** as of February 2026. Every major AI provider now ships MCP-compatible tooling.

## The 2026 roadmap

From the [Digital Applied March 2026 roundup](https://www.digitalapplied.com/blog/march-2026-ai-roundup-month-that-changed-everything), published 2026-03-09:

- **Streamable HTTP transport scaling** — moving past stdio as the default for production deployments
- **Tasks primitive lifecycle** — explicit long-running task support, not just one-shot tool calls
- **Enterprise SSO / audit** — making MCP palatable for regulated environments
- **Standard metadata format for registry discovery** — so agents can find MCP servers by capability, not by URL

## Official MCP servers observed

| Server | Publisher | Observed | Notes |
|---|---|---|---|
| Google Analytics MCP | Google | 2026-03-27 | **Noteworthy because it's Google, not a third-party.** v2.1 has 20 tools, OAuth, proactive alerting, content recommendations, multi-site dashboards. The validation signal matters more than the feature list. |
| Google Colab MCP | Google | 2026-04-11 | Any MCP client can drive a Colab notebook: execute cells, read outputs, attach data. Opens GPU-backed sandboxes to agents without re-implementing code execution. |
| WordPress Playground MCP | WordPress | 2026-04-11 | Official `@wp-playground/mcp`. Agents can spin up a full WordPress instance locally (PHP, FS, navigation) over WebSocket. Useful target for site-builder agents. |

## Community / third-party MCP servers

- **MCP server with 4M+ real US court opinions** — domain-specific legal research MCP (3/27)
- **"MCP server that turns Claude Code into a full agent OS"** — persistent memory, loop detection, audit trails (3/27)
- **FinMCP-Bench** — first benchmark specifically evaluating LLM agents using MCP for financial tool use. Research paper, 3/27.
- **MCP Subagents pattern** (Cameron Westland, 3/28) — using MCP as the coordination layer for subagent architectures

## Security posture

- **SurePath AI MCP Policy Controls** (3/27) — security controls for which MCP servers and tools AI clients can access. Framed as a shadow-IT risk as MCP adoption accelerates.
- **AgentGuard** (3/27) — open-source firewall for autonomous AI agents, now with MCP awareness.
- **AgentMint — OWASP compliance for AI agent tool calls** (4/10) — validates every tool call against OWASP rules before execution. Early example of the agent-tooling layer growing a compliance story.
- **Supply chain risk vector**: TeamPCP campaign (3/27, 3/28) compromised LiteLLM (a popular LLM-gateway / MCP-adjacent library). The attack surface around the MCP+LLM package ecosystem is under active, sustained attack.

## Why MCP matters for this vault

The retrieval layer of this vault runs over MCP — `qmd` exposes its hybrid search via the MCP server (`qmd mcp`). That's an instance of the broader pattern the briefings keep flagging: **agent memory and agent tools are increasingly delivered as MCP servers, not as in-process libraries**. The 97M downloads number tells you why: once you build to MCP, you work with every agent client by default.

See also:
- [[claude-code]] — the MCP client this vault is primarily consumed by
- [[agent-memory]] — the memory-infrastructure wave, a large fraction of which is packaged as MCP servers
- [[ai-coding-agents]] — the primary consumers of the MCP ecosystem

## Key queries this concept should answer

- "latest on MCP server development"
- "what's happening with MCP in 2026"
- "official MCP servers from Google"
- "is MCP becoming the standard agent protocol"
- "MCP security concerns"
- "supply chain risks in MCP packages"
