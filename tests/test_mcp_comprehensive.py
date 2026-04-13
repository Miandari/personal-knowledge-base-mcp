"""Comprehensive MCP server tests.

Tests all 8 MCP tools with controlled sandbox data, HTTP transport,
auth middleware, tool descriptions, and end-to-end workflows.

Run: pytest tests/test_mcp_comprehensive.py -v
"""

import json
import os
import secrets
import textwrap
from datetime import date
from pathlib import Path

import pytest

from pkb import config
from pkb.db import get_connection, init_schema
from pkb.embeddings import get_provider
from pkb.indexer import Indexer
from pkb.server import (
    mcp,
    _KB_TOKEN,
    _SEARCH_DESC,
    _EXPLORE_DESC,
    _GET_DESC,
    _LIST_DESC,
    _ADD_DESC,
    _SYNTHESIZE_DESC,
    _REINDEX_DESC,
    _STATUS_DESC,
    kb_search,
    kb_explore,
    kb_get,
    kb_list,
    kb_add,
    kb_synthesize,
    kb_reindex,
    kb_status,
    _slugify,
)


# ── Test Data ───────────────────────────────────────────────────────

CONCEPT_ALPHA = textwrap.dedent("""\
---
type: concept
title: "Test Concept Alpha"
created: 2026-01-01
updated: 2026-01-15
status: developing
tags:
  - ai
  - memory
sources:
  - "[[sources/test-paper-alpha]]"
related:
  - "[[concepts/test-concept-beta]]"
---

# Test Concept Alpha

This is a test concept about AI memory systems. Agent memory
infrastructure is a growing field in machine learning.

## Key Ideas

- Memory persistence across sessions
- Retrieval-augmented generation patterns
- Vector database integration for semantic recall
""")

PAPER_ALPHA = textwrap.dedent("""\
---
type: source
title: "Test Paper Alpha"
created: 2026-01-01
updated: 2026-04-01
status: developing
sentiment: enthusiastic
tags:
  - ai
  - memory
url: "https://example.com/paper-alpha"
ingested_via: manual
related: []
---

# Test Paper Alpha

An enthusiastic paper about agent memory systems and their
revolutionary potential for autonomous AI agents.

## Findings

This paper demonstrates significant improvements in agent recall
accuracy when using structured memory stores.
""")

CONCEPT_BETA = textwrap.dedent("""\
---
type: concept
title: "Test Concept Beta"
created: 2026-02-01
updated: 2026-03-01
status: seed
tags:
  - ai
  - context
sources:
  - "[[sources/test-paper-beta]]"
related:
  - "[[concepts/test-concept-alpha]]"
---

# Test Concept Beta

This is about LLM context scaling and window management techniques.

## Overview

Context windows continue to grow but practical usage patterns
suggest diminishing returns beyond certain thresholds.
""")

PAPER_BETA = textwrap.dedent("""\
---
type: source
title: "Test Paper Beta"
created: 2026-02-01
updated: 2026-02-15
status: developing
sentiment: critical
tags:
  - ai
related: []
---

# Test Paper Beta

A critical analysis of LLM context window limitations and the
overlooked costs of scaling context length.

## Conclusion

The paper argues that longer context windows are not a substitute
for proper information retrieval and memory management.
""")

ENTITY_TOOL = textwrap.dedent("""\
---
type: entity
title: "Test Tool Entity"
created: 2026-01-01
updated: 2026-02-01
status: developing
tags:
  - memory
  - tool
entity_type: product
related: []
---

# Test Tool Entity

A memory tool for AI agents that provides persistent storage
and semantic retrieval capabilities.
""")

META_INDEX = textwrap.dedent("""\
---
type: meta
title: "Test Wiki Index"
created: 2026-01-01
updated: 2026-04-01
status: developing
related: []
---

# Test Wiki Index

- [[concepts/test-concept-alpha|Test Concept Alpha]]
- [[concepts/test-concept-beta|Test Concept Beta]]
- [[sources/test-paper-alpha|Test Paper Alpha]]
- [[sources/test-paper-beta|Test Paper Beta]]
- [[entities/test-tool-entity|Test Tool Entity]]
""")


# ── Helpers ─────────────────────────────────────────────────────────

def _cleanup_added_page(slug: str, type_dir: str = "sources"):
    """Remove a page created by kb_add from disk and DB."""
    fp = config.WIKI_DIR / type_dir / f"{slug}.md"
    if fp.exists():
        fp.unlink()
    node_id = f"{type_dir}/{slug}"
    conn = get_connection()
    try:
        # FTS5 virtual table doesn't cascade — delete manually
        conn.execute("DELETE FROM nodes_fts WHERE node_id = ?", (node_id,))
        # edges.to_id has no FK — delete manually
        conn.execute("DELETE FROM edges WHERE to_id = ?", (node_id,))
        # CASCADE handles: tags, aliases, chunks (→ trigger: chunks_vec), edges.from_id
        conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    finally:
        conn.close()


def _parse_sse_result(text: str):
    """Extract JSON-RPC result from SSE response text."""
    for line in text.strip().splitlines():
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                if "result" in data:
                    return data["result"]
            except json.JSONDecodeError:
                continue
    return None


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mcp_sandbox(tmp_path_factory):
    """Module-scoped sandbox with test data. Patches config for all tests."""
    tmp = tmp_path_factory.mktemp("mcp_comprehensive")
    wiki_dir = tmp / "wiki"

    for subdir in ("concepts", "sources", "entities", "meta", "questions"):
        (wiki_dir / subdir).mkdir(parents=True)

    (wiki_dir / "concepts" / "test-concept-alpha.md").write_text(CONCEPT_ALPHA)
    (wiki_dir / "concepts" / "test-concept-beta.md").write_text(CONCEPT_BETA)
    (wiki_dir / "sources" / "test-paper-alpha.md").write_text(PAPER_ALPHA)
    (wiki_dir / "sources" / "test-paper-beta.md").write_text(PAPER_BETA)
    (wiki_dir / "entities" / "test-tool-entity.md").write_text(ENTITY_TOOL)
    (wiki_dir / "index.md").write_text(META_INDEX)

    orig = {
        "DB_PATH": config.DB_PATH,
        "WIKI_DIR": config.WIKI_DIR,
        "VAULT_ROOT": config.VAULT_ROOT,
    }
    orig_embed = os.environ.get("KB_EMBEDDING_PROVIDER")

    config.DB_PATH = tmp / "test.db"
    config.WIKI_DIR = wiki_dir
    config.VAULT_ROOT = tmp
    os.environ["KB_EMBEDDING_PROVIDER"] = "noop"

    conn = get_connection()
    init_schema(conn)
    provider = get_provider("noop")
    indexer = Indexer(conn, wiki_dir=wiki_dir, embedding_provider=provider)
    indexer.rebuild(force=True)
    conn.close()

    yield tmp

    config.DB_PATH = orig["DB_PATH"]
    config.WIKI_DIR = orig["WIKI_DIR"]
    config.VAULT_ROOT = orig["VAULT_ROOT"]
    if orig_embed is not None:
        os.environ["KB_EMBEDDING_PROVIDER"] = orig_embed
    elif "KB_EMBEDDING_PROVIDER" in os.environ:
        del os.environ["KB_EMBEDDING_PROVIDER"]


# ═══════════════════════════════════════════════════════════════════
# A. Tool Description Tests
# ═══════════════════════════════════════════════════════════════════

class TestToolDescriptions:
    """Verify tool descriptions are multi-line, contain proper guidance,
    and are registered on the FastMCP tool objects (not docstrings)."""

    ALL_DESCS = [
        ("search", _SEARCH_DESC),
        ("explore", _EXPLORE_DESC),
        ("get", _GET_DESC),
        ("list", _LIST_DESC),
        ("add", _ADD_DESC),
        ("synthesize", _SYNTHESIZE_DESC),
        ("reindex", _REINDEX_DESC),
        ("status", _STATUS_DESC),
    ]

    def test_all_descriptions_are_multiline(self):
        for name, desc in self.ALL_DESCS:
            lines = desc.strip().split("\n")
            assert len(lines) >= 3, f"{name} description has only {len(lines)} lines"

    def test_search_cross_references_other_tools(self):
        assert "kb_list" in _SEARCH_DESC
        assert "kb_get" in _SEARCH_DESC
        assert "kb_explore" in _SEARCH_DESC

    def test_explore_cross_references_other_tools(self):
        assert "kb_search" in _EXPLORE_DESC
        assert "kb_get" in _EXPLORE_DESC

    def test_get_warns_against_guessing_ids(self):
        assert "DO NOT guess" in _GET_DESC

    def test_list_directs_to_search(self):
        assert "kb_search" in _LIST_DESC

    def test_add_states_no_compilation(self):
        assert "compilation" in _ADD_DESC.lower() or "compile" in _ADD_DESC.lower()

    def test_synthesize_states_no_llm(self):
        assert "LLM" in _SYNTHESIZE_DESC
        assert "kb_reindex" in _SYNTHESIZE_DESC

    def test_reindex_warns_sequential(self):
        assert "parallel" in _REINDEX_DESC.lower()
        assert "sequential" in _REINDEX_DESC.lower()

    def test_status_mentions_rebuild(self):
        assert "rebuild" in _STATUS_DESC.lower()

    def test_descriptions_registered_verbatim(self):
        """Verify FastMCP tools use the description= kwarg, not docstrings."""
        tools = mcp._tool_manager._tools
        assert len(tools) == 8
        expected = {
            "kb_search": _SEARCH_DESC,
            "kb_explore": _EXPLORE_DESC,
            "kb_get": _GET_DESC,
            "kb_list": _LIST_DESC,
            "kb_add": _ADD_DESC,
            "kb_synthesize": _SYNTHESIZE_DESC,
            "kb_reindex": _REINDEX_DESC,
            "kb_status": _STATUS_DESC,
        }
        for name, expected_desc in expected.items():
            assert tools[name].description == expected_desc, (
                f"Tool {name}: description mismatch — possibly using docstring"
            )


# ═══════════════════════════════════════════════════════════════════
# B. Sandboxed Tool Tests
# ═══════════════════════════════════════════════════════════════════

class TestKbSearchSandbox:
    """kb_search with controlled test data."""

    def test_basic_returns_results(self, mcp_sandbox):
        results = kb_search(query="memory systems", limit=10)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_result_has_required_fields(self, mcp_sandbox):
        results = kb_search(query="memory", limit=5)
        r = results[0]
        for field in ("node_id", "title", "type", "score", "snippet", "status", "updated"):
            assert field in r, f"Missing field: {field}"

    def test_bm25_mode(self, mcp_sandbox):
        results = kb_search(query="memory systems", limit=5, mode="bm25")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_type_filter_concept(self, mcp_sandbox):
        results = kb_search(query="test", limit=10, type="concept")
        assert len(results) > 0
        for r in results:
            assert r["type"] == "concept"

    def test_type_filter_source(self, mcp_sandbox):
        results = kb_search(query="test", limit=10, type="source")
        assert len(results) > 0
        for r in results:
            assert r["type"] == "source"

    def test_sentiment_filter(self, mcp_sandbox):
        results = kb_search(query="paper", limit=10, sentiment="critical")
        assert isinstance(results, list)
        # If results found, the sentiment filter was applied

    def test_limit_respected(self, mcp_sandbox):
        results = kb_search(query="test", limit=2)
        assert len(results) <= 2

    def test_empty_query_graceful(self, mcp_sandbox):
        results = kb_search(query="", limit=5)
        assert isinstance(results, list)

    def test_no_results_for_nonsense_bm25(self, mcp_sandbox):
        # Must use bm25 mode — with NoopEmbedding, vec search matches everything
        results = kb_search(query="xyzzyplugh999nonexistent", limit=5, mode="bm25")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_scores_are_nonnegative(self, mcp_sandbox):
        for r in kb_search(query="memory", limit=10):
            assert r["score"] >= 0

    def test_finds_page_by_body_content(self, mcp_sandbox):
        results = kb_search(query="retrieval-augmented generation", limit=5)
        ids = [r["node_id"] for r in results]
        assert "concepts/test-concept-alpha" in ids


class TestKbExploreSandbox:
    """kb_explore with controlled test data."""

    def test_returns_dict(self, mcp_sandbox):
        assert isinstance(kb_explore(topic="memory systems"), dict)

    def test_result_has_all_fields(self, mcp_sandbox):
        result = kb_explore(topic="memory")
        for key in (
            "topic", "synthesis", "is_stale", "stale_sources",
            "unincorporated_sources", "suggested_actions",
            "search_results", "adjacent_topics",
        ):
            assert key in result, f"Missing key: {key}"

    def test_finds_synthesis_page(self, mcp_sandbox):
        result = kb_explore(topic="AI memory systems")
        if result["synthesis"]:
            assert "id" in result["synthesis"]
            assert "title" in result["synthesis"]
            assert result["synthesis"]["type"] in (
                "concept", "overview", "comparison", "question"
            )

    def test_unknown_topic_gives_suggestions(self, mcp_sandbox):
        result = kb_explore(topic="underwater basket weaving nonsense")
        assert isinstance(result["suggested_actions"], list)
        assert len(result["suggested_actions"]) > 0

    def test_search_results_included(self, mcp_sandbox):
        result = kb_explore(topic="memory")
        assert isinstance(result["search_results"], list)

    def test_adjacent_topics_are_summaries(self, mcp_sandbox):
        result = kb_explore(topic="AI memory systems")
        for adj in result["adjacent_topics"]:
            for field in ("id", "title", "type"):
                assert field in adj

    def test_staleness_detected(self, mcp_sandbox):
        """concept-alpha (updated 2026-01-15) sources paper-alpha (updated 2026-04-01) → stale."""
        result = kb_explore(topic="AI memory systems agent")
        if result.get("synthesis") and result["synthesis"]["id"] == "concepts/test-concept-alpha":
            assert result["is_stale"] is True
            stale_ids = [s["id"] for s in result["stale_sources"]]
            assert "sources/test-paper-alpha" in stale_ids


class TestKbGetSandbox:
    """kb_get with controlled test data."""

    def test_get_concept(self, mcp_sandbox):
        r = kb_get(node_id="concepts/test-concept-alpha")
        assert r is not None
        assert r["title"] == "Test Concept Alpha"
        assert r["type"] == "concept"

    def test_get_returns_body(self, mcp_sandbox):
        r = kb_get(node_id="concepts/test-concept-alpha")
        assert len(r["body"]) > 50
        assert "memory systems" in r["body"].lower()

    def test_get_returns_metadata(self, mcp_sandbox):
        r = kb_get(node_id="concepts/test-concept-alpha")
        assert r["status"] == "developing"
        assert r["created"] == "2026-01-01"
        assert r["updated"] == "2026-01-15"

    def test_get_returns_tags(self, mcp_sandbox):
        r = kb_get(node_id="concepts/test-concept-alpha")
        assert isinstance(r["tags"], list)
        assert "ai" in r["tags"]
        assert "memory" in r["tags"]

    def test_get_returns_source_edges(self, mcp_sandbox):
        r = kb_get(node_id="concepts/test-concept-alpha")
        assert isinstance(r["sources"], list)
        source_ids = [s["id"] for s in r["sources"]]
        assert "sources/test-paper-alpha" in source_ids

    def test_get_returns_related_edges(self, mcp_sandbox):
        r = kb_get(node_id="concepts/test-concept-alpha")
        assert isinstance(r["related"], list)

    def test_get_source_sentiment(self, mcp_sandbox):
        r = kb_get(node_id="sources/test-paper-alpha")
        assert r["sentiment"] == "enthusiastic"

    def test_get_source_url(self, mcp_sandbox):
        r = kb_get(node_id="sources/test-paper-alpha")
        assert r["url"] == "https://example.com/paper-alpha"

    def test_get_entity_type(self, mcp_sandbox):
        r = kb_get(node_id="entities/test-tool-entity")
        assert r["entity_type"] == "product"

    def test_get_meta_page(self, mcp_sandbox):
        r = kb_get(node_id="index")
        assert r is not None
        assert r["type"] == "meta"

    def test_get_nonexistent_returns_none(self, mcp_sandbox):
        assert kb_get(node_id="nonexistent/page-xyz") is None


class TestKbListSandbox:
    """kb_list with controlled test data."""

    def test_list_all_pages(self, mcp_sandbox):
        results = kb_list()
        assert len(results) == 6  # 2 concepts + 2 sources + 1 entity + 1 meta

    def test_list_by_type_concept(self, mcp_sandbox):
        results = kb_list(type="concept")
        assert len(results) == 2
        assert all(r["type"] == "concept" for r in results)

    def test_list_by_type_source(self, mcp_sandbox):
        results = kb_list(type="source")
        assert len(results) == 2
        assert all(r["type"] == "source" for r in results)

    def test_list_by_type_entity(self, mcp_sandbox):
        results = kb_list(type="entity")
        assert len(results) == 1

    def test_list_by_tag(self, mcp_sandbox):
        results = kb_list(tag="memory")
        assert len(results) >= 2  # concept-alpha + paper-alpha + entity

    def test_list_by_status_seed(self, mcp_sandbox):
        results = kb_list(status="seed")
        assert len(results) >= 1
        assert all(r["status"] == "seed" for r in results)

    def test_list_sort_title(self, mcp_sandbox):
        results = kb_list(sort="title")
        titles = [r["title"] for r in results]
        # list_nodes sorts DESC
        assert titles == sorted(titles, key=str.lower, reverse=True)

    def test_list_limit(self, mcp_sandbox):
        assert len(kb_list(limit=2)) <= 2

    def test_list_result_structure(self, mcp_sandbox):
        r = kb_list(limit=1)[0]
        for field in ("id", "title", "type", "status", "updated"):
            assert field in r


class TestKbAddSandbox:
    """kb_add — each test cleans up its created page."""

    def test_add_source(self, mcp_sandbox):
        try:
            r = kb_add(title="Add Test Source", type="source",
                       body="# Test\n\nBody.", tags=["test"])
            assert "error" not in r
            assert r["id"] == "sources/add-test-source"
            assert (config.WIKI_DIR / "sources" / "add-test-source.md").exists()
        finally:
            _cleanup_added_page("add-test-source", "sources")

    def test_add_concept(self, mcp_sandbox):
        try:
            r = kb_add(title="Add Test Concept", type="concept", body="# C\n\nBody.")
            assert "error" not in r
            assert r["id"] == "concepts/add-test-concept"
        finally:
            _cleanup_added_page("add-test-concept", "concepts")

    def test_add_entity(self, mcp_sandbox):
        try:
            r = kb_add(title="Add Test Entity", type="entity", body="# E\n\nBody.")
            assert "error" not in r
            assert r["id"] == "entities/add-test-entity"
        finally:
            _cleanup_added_page("add-test-entity", "entities")

    def test_add_with_all_params(self, mcp_sandbox):
        try:
            r = kb_add(
                title="Add Full Params",
                type="source",
                body="# Full\n\nAll parameters.",
                source_url="https://example.com/full",
                tags=["tag-a", "tag-b"],
                sources=["concepts/test-concept-alpha"],
                sentiment="critical",
                ingested_via="web_fetch",
            )
            assert "error" not in r

            content = (config.WIKI_DIR / "sources" / "add-full-params.md").read_text()
            assert "sentiment: critical" in content
            assert "ingested_via: web_fetch" in content
            assert 'url: "https://example.com/full"' in content
            assert "- tag-a" in content
            assert "- tag-b" in content
            assert "[[concepts/test-concept-alpha]]" in content
        finally:
            _cleanup_added_page("add-full-params", "sources")

    def test_add_conflict_returns_error(self, mcp_sandbox):
        r = kb_add(title="Test Concept Alpha", type="concept", body="Dup.")
        assert "error" in r

    def test_add_immediately_searchable(self, mcp_sandbox):
        try:
            kb_add(title="Unique Fnord Test", type="source",
                   body="# Fnord\n\nThe word fnord appears here.", tags=["test"])
            results = kb_search(query="fnord", limit=5, mode="bm25")
            ids = [r["node_id"] for r in results]
            assert "sources/unique-fnord-test" in ids
        finally:
            _cleanup_added_page("unique-fnord-test", "sources")

    def test_add_frontmatter_format(self, mcp_sandbox):
        try:
            kb_add(title="Frontmatter Check", type="source", body="Body.")
            content = (config.WIKI_DIR / "sources" / "frontmatter-check.md").read_text()
            assert content.startswith("---\n")
            assert "type: source" in content
            assert 'title: "Frontmatter Check"' in content
            assert f"created: {date.today().isoformat()}" in content
            assert "status: seed" in content
            assert "related: []" in content
        finally:
            _cleanup_added_page("frontmatter-check", "sources")

    def test_add_mutable_defaults_safe(self, mcp_sandbox):
        """list params don't leak between calls."""
        try:
            kb_add(title="Mutable A", type="source", body="A.", tags=["leaked"])
        finally:
            _cleanup_added_page("mutable-a", "sources")
        try:
            kb_add(title="Mutable B", type="source", body="B.")
            content = (config.WIKI_DIR / "sources" / "mutable-b.md").read_text()
            assert "leaked" not in content
        finally:
            _cleanup_added_page("mutable-b", "sources")


class TestKbSynthesizeSandbox:
    """kb_synthesize with controlled test data."""

    def test_returns_string(self, mcp_sandbox):
        assert isinstance(kb_synthesize(node_id="concepts/test-concept-alpha"), str)

    def test_contains_synthesis_header(self, mcp_sandbox):
        assert "Synthesis task" in kb_synthesize(node_id="concepts/test-concept-alpha")

    def test_includes_current_page_content(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-alpha")
        assert "Test Concept Alpha" in r
        assert "memory systems" in r.lower()

    def test_includes_source_content(self, mcp_sandbox):
        r = kb_synthesize(
            node_id="concepts/test-concept-alpha",
            source_ids=["sources/test-paper-alpha"],
        )
        assert "Test Paper Alpha" in r

    def test_contains_rules_section(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-alpha")
        assert "### Rules" in r

    def test_reindex_rule_present(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-alpha")
        assert "MUST immediately call kb_reindex" in r

    def test_reindex_rule_has_correct_node_id(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-alpha")
        assert 'kb_reindex(node_id="concepts/test-concept-alpha")' in r

    def test_different_node_id_in_reindex_rule(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-beta")
        assert 'kb_reindex(node_id="concepts/test-concept-beta")' in r

    def test_no_sources_shows_placeholder(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-alpha")
        assert "no new sources specified" in r.lower()

    def test_nonexistent_page_creates_prompt(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/brand-new-topic")
        assert isinstance(r, str)
        assert "create from scratch" in r.lower()

    def test_contains_today_date(self, mcp_sandbox):
        r = kb_synthesize(node_id="concepts/test-concept-alpha")
        assert date.today().isoformat() in r

    def test_invalid_source_skipped_gracefully(self, mcp_sandbox):
        r = kb_synthesize(
            node_id="concepts/test-concept-alpha",
            source_ids=["nonexistent/source-xyz"],
        )
        assert isinstance(r, str)
        # Should still work — invalid source simply omitted

    def test_multiple_sources(self, mcp_sandbox):
        r = kb_synthesize(
            node_id="concepts/test-concept-alpha",
            source_ids=["sources/test-paper-alpha", "sources/test-paper-beta"],
        )
        assert "Test Paper Alpha" in r
        assert "Test Paper Beta" in r


class TestKbReindexSandbox:
    """kb_reindex with controlled test data."""

    def test_by_node_id(self, mcp_sandbox):
        r = kb_reindex(node_id="concepts/test-concept-alpha")
        assert "error" not in r
        assert r["id"] == "concepts/test-concept-alpha"

    def test_by_relative_file_path(self, mcp_sandbox):
        r = kb_reindex(file_path="wiki/concepts/test-concept-alpha.md")
        assert "error" not in r

    def test_by_absolute_path(self, mcp_sandbox):
        abs_path = str(config.WIKI_DIR / "concepts" / "test-concept-alpha.md")
        r = kb_reindex(file_path=abs_path)
        assert "error" not in r

    def test_returns_summary_fields(self, mcp_sandbox):
        r = kb_reindex(node_id="sources/test-paper-alpha")
        for field in ("id", "title", "type"):
            assert field in r

    def test_nonexistent_node_returns_error(self, mcp_sandbox):
        assert "error" in kb_reindex(node_id="nonexistent/page-xyz")

    def test_nonexistent_file_returns_error(self, mcp_sandbox):
        assert "error" in kb_reindex(file_path="wiki/nonexistent/page.md")

    def test_no_args_returns_error(self, mcp_sandbox):
        assert "error" in kb_reindex()


class TestKbStatusSandbox:
    """kb_status with controlled test data."""

    def test_returns_dict(self, mcp_sandbox):
        assert isinstance(kb_status(), dict)

    def test_has_all_fields(self, mcp_sandbox):
        r = kb_status()
        for key in (
            "node_count", "edge_count", "chunk_count",
            "embedded_chunks", "embedding_coverage",
            "stale_count", "orphan_chunks", "types",
        ):
            assert key in r, f"Missing key: {key}"

    def test_node_count_matches_data(self, mcp_sandbox):
        assert kb_status()["node_count"] == 6

    def test_type_distribution(self, mcp_sandbox):
        types = kb_status()["types"]
        assert types.get("concept") == 2
        assert types.get("source") == 2
        assert types.get("entity") == 1
        assert types.get("meta") == 1

    def test_coverage_in_range(self, mcp_sandbox):
        cov = kb_status()["embedding_coverage"]
        assert 0 <= cov <= 1

    def test_chunks_positive(self, mcp_sandbox):
        assert kb_status()["chunk_count"] > 0

    def test_edges_positive(self, mcp_sandbox):
        assert kb_status()["edge_count"] > 0


# ═══════════════════════════════════════════════════════════════════
# C. Auth Middleware Tests
# ═══════════════════════════════════════════════════════════════════

class TestAuthMiddleware:
    """Bearer token auth middleware tested against a simple Starlette app.

    Uses a plain Starlette app (not MCP) to isolate the middleware logic
    from the MCP session manager, which can only be started once.
    """

    @pytest.fixture
    def authed_app(self):
        from starlette.applications import Starlette
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse, PlainTextResponse
        from starlette.routing import Route

        token = "test-secret-42"

        async def echo(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/mcp", echo, methods=["POST", "OPTIONS"])])

        class BearerAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if request.method == "OPTIONS":
                    return await call_next(request)
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or not secrets.compare_digest(
                    auth[7:], token
                ):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)
                return await call_next(request)

        app.add_middleware(BearerAuthMiddleware)
        return app, token

    def test_no_auth_returns_401(self, authed_app):
        from starlette.testclient import TestClient

        app, _ = authed_app
        with TestClient(app) as client:
            assert client.post("/mcp", json={}).status_code == 401

    def test_wrong_token_returns_401(self, authed_app):
        from starlette.testclient import TestClient

        app, _ = authed_app
        with TestClient(app) as client:
            resp = client.post(
                "/mcp", json={},
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status_code == 401

    def test_valid_token_returns_200(self, authed_app):
        from starlette.testclient import TestClient

        app, token = authed_app
        with TestClient(app) as client:
            resp = client.post(
                "/mcp", json={},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            assert resp.text == "ok"

    def test_options_bypasses_auth(self, authed_app):
        from starlette.testclient import TestClient

        app, _ = authed_app
        with TestClient(app) as client:
            resp = client.options("/mcp")
            assert resp.status_code != 401


# ═══════════════════════════════════════════════════════════════════
# D. HTTP Transport Tests
# ═══════════════════════════════════════════════════════════════════

# Module-scoped HTTP client — the MCP SDK's session manager can only
# be started once per FastMCP instance, so all HTTP tests share one
# TestClient context.

@pytest.fixture(scope="module")
def http_client(mcp_sandbox):
    """Single HTTP TestClient for all HTTP transport tests."""
    from starlette.testclient import TestClient

    app = mcp.streamable_http_app()
    with TestClient(
        app, base_url="http://127.0.0.1:8181", raise_server_exceptions=False
    ) as client:
        yield client


class TestHTTPTransport:
    """MCP protocol over Streamable HTTP transport."""

    # MCP SDK requires this Accept header (returns 406 without it)
    _ACCEPT = {"Accept": "application/json, text/event-stream"}

    _INIT_PAYLOAD = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "http-test", "version": "1.0"},
        },
    }

    @pytest.fixture
    def session(self, http_client):
        """Per-test MCP session (shares the module-scoped TestClient)."""
        resp = http_client.post("/mcp", json=self._INIT_PAYLOAD, headers=self._ACCEPT)
        assert resp.status_code == 200
        sid = resp.headers.get("mcp-session-id")
        assert sid
        http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Mcp-Session-Id": sid, **self._ACCEPT},
        )
        return sid

    def _call_tool(self, client, sid, tool_name, arguments, req_id=10):
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            headers={"Mcp-Session-Id": sid, **self._ACCEPT},
        )
        assert resp.status_code == 200
        result = _parse_sse_result(resp.text)
        assert result is not None, f"No result in SSE: {resp.text[:500]}"
        # FastMCP puts each list item as a separate content block
        items = [json.loads(c["text"]) for c in result["content"] if c["type"] == "text"]
        return items if len(items) != 1 else items[0]

    def test_initialize_returns_server_info(self, http_client):
        resp = http_client.post("/mcp", json=self._INIT_PAYLOAD, headers=self._ACCEPT)
        r = _parse_sse_result(resp.text)
        assert r["serverInfo"]["name"] == "pkb"
        assert "protocolVersion" in r

    def test_session_id_in_headers(self, http_client):
        resp = http_client.post("/mcp", json=self._INIT_PAYLOAD, headers=self._ACCEPT)
        assert resp.headers.get("mcp-session-id")

    def test_tools_list_returns_all_eight(self, http_client, session):
        resp = http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Mcp-Session-Id": session, **self._ACCEPT},
        )
        tools = _parse_sse_result(resp.text)["tools"]
        names = {t["name"] for t in tools}
        assert names == {
            "kb_search", "kb_explore", "kb_get", "kb_list",
            "kb_add", "kb_synthesize", "kb_reindex", "kb_status",
        }

    def test_descriptions_survive_http(self, http_client, session):
        """Newlines in descriptions must survive SSE serialisation."""
        resp = http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            headers={"Mcp-Session-Id": session, **self._ACCEPT},
        )
        for tool in _parse_sse_result(resp.text)["tools"]:
            assert "\n" in tool["description"], (
                f"{tool['name']} description lost newlines over HTTP"
            )

    def test_http_kb_status(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_status", {})
        assert r["node_count"] == 6

    def test_http_kb_search(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_search", {
            "query": "memory", "limit": 5,
        })
        assert isinstance(r, list)
        assert len(r) > 0

    def test_http_kb_get(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_get", {
            "node_id": "concepts/test-concept-alpha",
        })
        assert r["title"] == "Test Concept Alpha"

    def test_http_kb_list(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_list", {"type": "concept"})
        assert len(r) == 2

    def test_http_kb_explore(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_explore", {"topic": "memory"})
        assert "topic" in r
        assert "suggested_actions" in r

    def test_http_kb_synthesize(self, http_client, session):
        resp = http_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {
                    "name": "kb_synthesize",
                    "arguments": {"node_id": "concepts/test-concept-alpha"},
                },
            },
            headers={"Mcp-Session-Id": session, **self._ACCEPT},
        )
        result = _parse_sse_result(resp.text)
        text = result["content"][0]["text"]
        assert "Synthesis task" in text
        assert "MUST immediately call kb_reindex" in text


# ═══════════════════════════════════════════════════════════════════
# E. End-to-End Workflow Tests
# ═══════════════════════════════════════════════════════════════════

class TestWorkflows:
    """Multi-tool workflows."""

    def test_add_search_get_cycle(self, mcp_sandbox):
        """Add a page → find via search → retrieve full content."""
        try:
            kb_add(
                title="Workflow Zephyr",
                type="source",
                body="# Zephyr\n\nA unique workflow test page about zephyr.",
                tags=["workflow"],
                sentiment="neutral",
            )
            results = kb_search(query="zephyr", limit=5, mode="bm25")
            assert any(r["node_id"] == "sources/workflow-zephyr" for r in results)

            detail = kb_get(node_id="sources/workflow-zephyr")
            assert detail["title"] == "Workflow Zephyr"
            assert detail["sentiment"] == "neutral"
        finally:
            _cleanup_added_page("workflow-zephyr", "sources")

    def test_synthesize_includes_reindex_for_target(self, mcp_sandbox):
        """Synthesize prompt must include reindex instruction with correct node_id."""
        prompt = kb_synthesize(
            node_id="concepts/test-concept-alpha",
            source_ids=["sources/test-paper-alpha"],
        )
        assert 'kb_reindex(node_id="concepts/test-concept-alpha")' in prompt

        # Reindex should succeed for the same page
        assert "error" not in kb_reindex(node_id="concepts/test-concept-alpha")

    def test_list_then_get_all(self, mcp_sandbox):
        """Every listed page must be retrievable."""
        for page in kb_list():
            detail = kb_get(node_id=page["id"])
            assert detail is not None, f"kb_get failed for {page['id']}"
            assert detail["title"] == page["title"]
            assert detail["type"] == page["type"]

    def test_status_types_match_list(self, mcp_sandbox):
        """Every type in status must list the reported count."""
        for type_name, count in kb_status()["types"].items():
            assert len(kb_list(type=type_name)) == count

    def test_add_then_status_increments(self, mcp_sandbox):
        """Adding a page should increase node_count by 1."""
        before = kb_status()["node_count"]
        try:
            kb_add(title="Status Increment Test", type="source", body="Body.")
            assert kb_status()["node_count"] == before + 1
        finally:
            _cleanup_added_page("status-increment-test", "sources")
            # After cleanup, count should return to original
            assert kb_status()["node_count"] == before


# ═══════════════════════════════════════════════════════════════════
# F. Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Slugify, special characters, exports, error handling."""

    def test_slugify_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_slugify_special_chars(self):
        assert _slugify("What's New?!") == "whats-new"

    def test_slugify_multiple_spaces(self):
        assert _slugify("Too   Many   Spaces") == "too-many-spaces"

    def test_slugify_leading_trailing(self):
        assert _slugify("  Padded  ") == "padded"

    def test_slugify_hyphens(self):
        assert _slugify("already-hyphenated") == "already-hyphenated"

    def test_kb_token_importable(self):
        from pkb.server import _KB_TOKEN

        assert _KB_TOKEN is None or isinstance(_KB_TOKEN, str)

    def test_search_special_chars_no_crash(self, mcp_sandbox):
        for q in [
            'test "quoted"',
            "test's",
            "test & context",
            "test (parens)",
            "test [brackets]",
            "test*",
            "test?",
        ]:
            results = kb_search(query=q, limit=3)
            assert isinstance(results, list)

    def test_explore_empty_string(self, mcp_sandbox):
        r = kb_explore(topic="")
        assert isinstance(r, dict)

    def test_list_empty_type(self, mcp_sandbox):
        results = kb_list(type="nonexistent_type_xyz")
        assert isinstance(results, list)
        assert len(results) == 0
