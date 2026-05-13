"""Comprehensive MCP server tests.

Tests all 3 MCP tools (kb_find, kb_save, kb_status) with controlled sandbox
data, HTTP transport, auth middleware, tool descriptions, and end-to-end
workflows.

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
    _FIND_DESC,
    _SAVE_DESC,
    _STATUS_DESC,
    kb_find,
    kb_save,
    kb_status,
    _slugify,
)


# ── Test Data ───────────────────────────────────────────────────────

CONCEPT_ALPHA = textwrap.dedent("""\
---
origin: note
title: "Test Concept Alpha"
created_at: 2026-01-01
updated_at: 2026-01-15
tags:
  - ai
  - memory
sources:
  - "[[test-paper-alpha]]"
related:
  - "[[test-concept-beta]]"
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
origin: webpage
title: "Test Paper Alpha"
created_at: 2026-01-01
updated_at: 2026-04-01
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
origin: note
title: "Test Concept Beta"
created_at: 2026-02-01
updated_at: 2026-03-01
tags:
  - ai
  - context
sources:
  - "[[test-paper-beta]]"
related:
  - "[[test-concept-alpha]]"
---

# Test Concept Beta

This is about LLM context scaling and window management techniques.

## Overview

Context windows continue to grow but practical usage patterns
suggest diminishing returns beyond certain thresholds.
""")

PAPER_BETA = textwrap.dedent("""\
---
origin: webpage
title: "Test Paper Beta"
created_at: 2026-02-01
updated_at: 2026-02-15
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
origin: note
title: "Test Tool Entity"
created_at: 2026-01-01
updated_at: 2026-02-01
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
origin: meta
title: "Test Wiki Index"
created_at: 2026-01-01
updated_at: 2026-04-01
related: []
---

# Test Wiki Index

- [[test-concept-alpha|Test Concept Alpha]]
- [[test-concept-beta|Test Concept Beta]]
- [[test-paper-alpha|Test Paper Alpha]]
- [[test-paper-beta|Test Paper Beta]]
- [[test-tool-entity|Test Tool Entity]]
""")


# ── Helpers ─────────────────────────────────────────────────────────

def _cleanup_added_page(slug: str, type_dir: str = ""):
    """Remove a page created by kb_save from disk and DB."""
    fp = config.WIKI_DIR / f"{slug}.md"
    if fp.exists():
        fp.unlink()
    node_id = slug
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

    wiki_dir.mkdir(parents=True, exist_ok=True)

    (wiki_dir / "test-concept-alpha.md").write_text(CONCEPT_ALPHA)
    (wiki_dir / "test-concept-beta.md").write_text(CONCEPT_BETA)
    (wiki_dir / "test-paper-alpha.md").write_text(PAPER_ALPHA)
    (wiki_dir / "test-paper-beta.md").write_text(PAPER_BETA)
    (wiki_dir / "test-tool-entity.md").write_text(ENTITY_TOOL)
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
    and are registered on the FastMCP tool objects."""

    ALL_DESCS = [
        ("find", _FIND_DESC),
        ("save", _SAVE_DESC),
        ("status", _STATUS_DESC),
    ]

    def test_all_descriptions_are_multiline(self):
        for name, desc in self.ALL_DESCS:
            lines = desc.strip().split("\n")
            assert len(lines) >= 3, f"{name} description has only {len(lines)} lines"

    def test_find_warns_against_guessing_ids(self):
        assert "DO NOT guess" in _FIND_DESC

    def test_save_includes_usage_examples(self):
        assert "kb_save(" in _SAVE_DESC

    def test_status_mentions_rebuild(self):
        assert "rebuild" in _STATUS_DESC.lower()

    def test_descriptions_registered_verbatim(self):
        """Verify FastMCP tools use the description= kwarg."""
        tools = mcp._tool_manager._tools
        assert len(tools) == 3
        expected = {
            "kb_find": _FIND_DESC,
            "kb_save": _SAVE_DESC,
            "kb_status": _STATUS_DESC,
        }
        for name, expected_desc in expected.items():
            assert tools[name].description == expected_desc, (
                f"Tool {name}: description mismatch"
            )


# ═══════════════════════════════════════════════════════════════════
# B. Sandboxed Tool Tests
# ═══════════════════════════════════════════════════════════════════

class TestKbFindSearch:
    """kb_find with query= (search mode)."""

    def test_basic_returns_results(self, mcp_sandbox):
        results = kb_find(query="memory systems", limit=10)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_result_has_required_fields(self, mcp_sandbox):
        results = kb_find(query="memory", limit=5)
        r = results[0]
        for field in ("node_id", "title", "origin", "score", "snippet", "updated_at"):
            assert field in r, f"Missing field: {field}"

    def test_bm25_mode(self, mcp_sandbox):
        results = kb_find(query="memory systems", limit=5, mode="bm25")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_origin_filter(self, mcp_sandbox):
        results = kb_find(query="test", limit=10, origin="note")
        assert len(results) > 0
        for r in results:
            assert r["origin"] == "note"

    def test_origin_filter_webpage(self, mcp_sandbox):
        results = kb_find(query="test", limit=10, origin="webpage")
        assert len(results) > 0
        for r in results:
            assert r["origin"] == "webpage"

    def test_sentiment_filter(self, mcp_sandbox):
        results = kb_find(query="paper", limit=10, sentiment="critical")
        assert isinstance(results, list)

    def test_limit_respected(self, mcp_sandbox):
        results = kb_find(query="test", limit=2)
        assert len(results) <= 2

    def test_empty_query_graceful(self, mcp_sandbox):
        results = kb_find(query="", limit=5)
        assert isinstance(results, list)

    def test_no_results_for_nonsense_bm25(self, mcp_sandbox):
        results = kb_find(query="xyzzyplugh999nonexistent", limit=5, mode="bm25")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_scores_are_nonnegative(self, mcp_sandbox):
        for r in kb_find(query="memory", limit=10):
            assert r["score"] >= 0

    def test_finds_page_by_body_content(self, mcp_sandbox):
        results = kb_find(query="retrieval-augmented generation", limit=5)
        ids = [r["node_id"] for r in results]
        assert "test-concept-alpha" in ids


class TestKbFindGet:
    """kb_find with id= (get mode)."""

    def test_get_concept(self, mcp_sandbox):
        r = kb_find(id="test-concept-alpha")
        assert r is not None
        assert r["title"] == "Test Concept Alpha"
        assert r["origin"] == "note"

    def test_get_returns_body(self, mcp_sandbox):
        r = kb_find(id="test-concept-alpha")
        assert len(r["body"]) > 50
        assert "memory systems" in r["body"].lower()

    def test_get_returns_metadata(self, mcp_sandbox):
        r = kb_find(id="test-concept-alpha")
        assert r["origin"] == "note"
        assert r["created_at"] == "2026-01-01"
        assert r["updated_at"] == "2026-01-15"

    def test_get_returns_tags(self, mcp_sandbox):
        r = kb_find(id="test-concept-alpha")
        assert isinstance(r["tags"], list)
        assert "ai" in r["tags"]
        assert "memory" in r["tags"]

    def test_get_returns_source_edges(self, mcp_sandbox):
        r = kb_find(id="test-concept-alpha")
        assert isinstance(r["sources"], list)
        source_ids = [s["id"] for s in r["sources"]]
        assert "test-paper-alpha" in source_ids

    def test_get_returns_related_edges(self, mcp_sandbox):
        r = kb_find(id="test-concept-alpha")
        assert isinstance(r["related"], list)

    def test_get_source_sentiment(self, mcp_sandbox):
        r = kb_find(id="test-paper-alpha")
        assert r["sentiment"] == "enthusiastic"

    def test_get_source_url(self, mcp_sandbox):
        r = kb_find(id="test-paper-alpha")
        assert r["url"] == "https://example.com/paper-alpha"

    def test_get_entity_has_tags(self, mcp_sandbox):
        r = kb_find(id="test-tool-entity")
        assert "memory" in r["tags"] or "tool" in r["tags"]

    def test_get_meta_page(self, mcp_sandbox):
        r = kb_find(id="index")
        assert r is not None
        assert r["origin"] == "meta"

    def test_get_nonexistent_returns_none(self, mcp_sandbox):
        assert kb_find(id="nonexistent/page-xyz") is None


class TestKbFindList:
    """kb_find with filters (list mode)."""

    def test_list_all_pages(self, mcp_sandbox):
        results = kb_find(origin="note")
        # 2 concepts + 1 entity = 3 note-origin pages
        assert len(results) == 3
        assert all(r["origin"] == "note" for r in results)

    def test_list_by_origin_webpage(self, mcp_sandbox):
        results = kb_find(origin="webpage")
        assert len(results) == 2
        assert all(r["origin"] == "webpage" for r in results)

    def test_list_by_tag(self, mcp_sandbox):
        results = kb_find(tag="memory")
        assert len(results) >= 2

    def test_list_sort_title(self, mcp_sandbox):
        results = kb_find(origin="note", sort="title")
        titles = [r["title"] for r in results]
        assert titles == sorted(titles, key=str.lower, reverse=True)

    def test_list_limit(self, mcp_sandbox):
        assert len(kb_find(origin="note", limit=2)) <= 2

    def test_list_result_structure(self, mcp_sandbox):
        r = kb_find(origin="note", limit=1)[0]
        for field in ("id", "title", "origin", "updated_at"):
            assert field in r

    def test_no_params_returns_list(self, mcp_sandbox):
        """Empty query returns empty or all results, not an error."""
        r = kb_find()
        assert isinstance(r, list)

    def test_bare_browse_returns_pages(self, mcp_sandbox):
        """kb_find() with no id, no query, no filters should browse — not return [].
        Regression: pre-fix this routed to the empty-query search path and yielded 0."""
        r = kb_find()
        assert isinstance(r, list)
        assert len(r) >= 1, "bare kb_find() must return pages, not empty"

    def test_browse_sort_created_at(self, mcp_sandbox):
        """`kb_find(sort='created_at')` with no other params should list by created_at."""
        r = kb_find(sort="created_at", limit=10)
        assert isinstance(r, list)
        assert len(r) >= 1
        # Created dates should be sorted descending (most recent first)
        cdates = [n.get("created_at") for n in r if n.get("created_at")]
        assert cdates == sorted(cdates, reverse=True)

    def test_browse_date_filter_only(self, mcp_sandbox):
        """kb_find(created_after=…) with no other params should browse, not search."""
        # Fixture pages have created_at: 2026-01-01; anything earlier than that
        # cutoff means "show everything created on or after 2026-01-01" → all pages.
        r = kb_find(created_after="2026-01-01", sort="created_at")
        assert isinstance(r, list)
        assert len(r) >= 1
        for n in r:
            assert n["created_at"] >= "2026-01-01"


class TestKbSaveCreate:
    """kb_save creating new pages."""

    def test_create_source(self, mcp_sandbox):
        try:
            r = kb_save(title="Add Test Source", origin="webpage",
                        body="# Test\n\nBody.", tags=["test"])
            assert "error" not in r
            assert r["id"] == "add-test-source"
            assert (config.WIKI_DIR / "add-test-source.md").exists()
        finally:
            _cleanup_added_page("add-test-source")

    def test_create_concept(self, mcp_sandbox):
        try:
            r = kb_save(title="Add Test Concept", origin="note", body="# C\n\nBody.")
            assert "error" not in r
            assert r["id"] == "add-test-concept"
        finally:
            _cleanup_added_page("add-test-concept")

    def test_create_with_all_params(self, mcp_sandbox):
        try:
            r = kb_save(
                title="Add Full Params",
                origin="webpage",
                body="# Full\n\nAll parameters.",
                source_url="https://example.com/full",
                tags=["tag-a", "tag-b"],
                sources=["test-concept-alpha"],
                sentiment="critical",
                ingested_via="web_fetch",
            )
            assert "error" not in r

            content = (config.WIKI_DIR / "add-full-params.md").read_text()
            assert "sentiment: critical" in content
            assert "ingested_via: web_fetch" in content
            assert 'url: "https://example.com/full"' in content
            assert "- tag-a" in content
            assert "- tag-b" in content
            assert "[[test-concept-alpha]]" in content
        finally:
            _cleanup_added_page("add-full-params")

    def test_conflict_returns_error(self, mcp_sandbox):
        r = kb_save(title="Test Concept Alpha", origin="note", body="Dup.")
        assert "error" in r

    def test_immediately_searchable(self, mcp_sandbox):
        try:
            kb_save(title="Unique Fnord Test", origin="webpage",
                    body="# Fnord\n\nThe word fnord appears here.", tags=["test"])
            results = kb_find(query="fnord", limit=5, mode="bm25")
            ids = [r["node_id"] for r in results]
            assert "unique-fnord-test" in ids
        finally:
            _cleanup_added_page("unique-fnord-test")

    def test_frontmatter_format(self, mcp_sandbox):
        try:
            kb_save(title="Frontmatter Check", origin="webpage", body="Body.")
            content = (config.WIKI_DIR / "frontmatter-check.md").read_text()
            assert content.startswith("---\n")
            assert "origin: webpage" in content
            assert 'title: "Frontmatter Check"' in content
            assert f"created_at: {date.today().isoformat()}" in content
            # status field has been retired; new pages must NOT emit it.
            assert "status:" not in content
            assert "related: []" in content
        finally:
            _cleanup_added_page("frontmatter-check")

    def test_mutable_defaults_safe(self, mcp_sandbox):
        """list params don't leak between calls."""
        try:
            kb_save(title="Mutable A", origin="webpage", body="A.", tags=["leaked"])
        finally:
            _cleanup_added_page("mutable-a")
        try:
            kb_save(title="Mutable B", origin="webpage", body="B.")
            content = (config.WIKI_DIR / "mutable-b.md").read_text()
            assert "leaked" not in content
        finally:
            _cleanup_added_page("mutable-b")

    def test_missing_origin_returns_error(self, mcp_sandbox):
        r = kb_save(title="No Origin", body="Body.")
        assert "error" in r


class TestKbSaveReindex:
    """kb_save reindex mode (id only, no body or metadata)."""

    def test_by_node_id(self, mcp_sandbox):
        r = kb_save(id="test-concept-alpha")
        assert "error" not in r
        assert r["id"] == "test-concept-alpha"

    def test_returns_summary_fields(self, mcp_sandbox):
        r = kb_save(id="test-paper-alpha")
        for field in ("id", "title", "origin"):
            assert field in r

    def test_nonexistent_node_returns_error(self, mcp_sandbox):
        assert "error" in kb_save(id="nonexistent/page-xyz")


class TestKbSaveSectionUpdate:
    """kb_save section update mode (id + section + body)."""

    def test_insert_new_section(self, mcp_sandbox):
        try:
            kb_save(title="Section Test", origin="note",
                    body="# Section Test\n\n## Notes\n\nOriginal notes.")
            r = kb_save(id="section-test", section="Summary", body="A new summary.")
            assert "error" not in r
            content = (config.WIKI_DIR / "section-test.md").read_text()
            assert "## Summary" in content
            assert "A new summary." in content
            assert "## Notes" in content
            assert "Original notes." in content
        finally:
            _cleanup_added_page("section-test")

    def test_replace_existing_section(self, mcp_sandbox):
        try:
            kb_save(title="Replace Section", origin="note",
                    body="# Replace Section\n\n## Summary\n\nOld summary.\n\n## Notes\n\nKeep this.")
            r = kb_save(id="replace-section", section="Summary", body="New summary content.")
            assert "error" not in r
            content = (config.WIKI_DIR / "replace-section.md").read_text()
            assert "New summary content." in content
            assert "Old summary." not in content
            assert "Keep this." in content
        finally:
            _cleanup_added_page("replace-section")


class TestKbSaveFrontmatterUpdate:
    """kb_save frontmatter-only updates (replace semantics)."""

    def test_replace_tags(self, mcp_sandbox):
        """tags=[...] replaces the entire tag list."""
        try:
            kb_save(title="FM Update Test", origin="note", body="Body.", tags=["original"])
            r = kb_save(id="fm-update-test", tags=["new-tag"])
            assert "error" not in r
            content = (config.WIKI_DIR / "fm-update-test.md").read_text()
            assert "- new-tag" in content
            assert "- original" not in content
        finally:
            _cleanup_added_page("fm-update-test")

    def test_replace_tags_preserves_all(self, mcp_sandbox):
        """Passing all desired tags keeps them all."""
        try:
            kb_save(title="FM Keep Tags", origin="note", body="Body.", tags=["a", "b"])
            r = kb_save(id="fm-keep-tags", tags=["a", "b", "c"])
            assert "error" not in r
            content = (config.WIKI_DIR / "fm-keep-tags.md").read_text()
            assert "- a" in content
            assert "- b" in content
            assert "- c" in content
        finally:
            _cleanup_added_page("fm-keep-tags")

    def test_clear_tags(self, mcp_sandbox):
        """tags=[] clears all tags."""
        try:
            kb_save(title="FM Clear Tags", origin="note", body="Body.", tags=["remove-me"])
            r = kb_save(id="fm-clear-tags", tags=[])
            assert "error" not in r
            content = (config.WIKI_DIR / "fm-clear-tags.md").read_text()
            assert "- remove-me" not in content
            assert "tags: []" in content
        finally:
            _cleanup_added_page("fm-clear-tags")

    def test_omit_tags_leaves_unchanged(self, mcp_sandbox):
        """Not passing tags at all leaves them unchanged."""
        try:
            kb_save(title="FM Omit Tags", origin="note", body="Body.", tags=["keep-me"])
            r = kb_save(id="fm-omit-tags", sentiment="neutral")
            assert "error" not in r
            content = (config.WIKI_DIR / "fm-omit-tags.md").read_text()
            assert "- keep-me" in content
        finally:
            _cleanup_added_page("fm-omit-tags")

    def test_replace_related(self, mcp_sandbox):
        """related=[...] replaces the related list."""
        try:
            kb_save(title="FM Related Test", origin="note", body="Body.",
                    related=["test-concept-alpha"])
            r = kb_save(id="fm-related-test", related=["test-concept-beta"])
            assert "error" not in r
            content = (config.WIKI_DIR / "fm-related-test.md").read_text()
            assert "[[test-concept-beta]]" in content
            assert "[[test-concept-alpha]]" not in content
        finally:
            _cleanup_added_page("fm-related-test")


class TestKbStatus:
    """kb_status health check."""

    def test_returns_dict(self, mcp_sandbox):
        assert isinstance(kb_status(), dict)

    def test_has_all_fields(self, mcp_sandbox):
        r = kb_status()
        for key in (
            "node_count", "edge_count", "chunk_count",
            "embedded_chunks", "embedding_coverage",
            "stale_count", "orphan_chunks", "origins",
        ):
            assert key in r, f"Missing key: {key}"

    def test_node_count_matches_data(self, mcp_sandbox):
        assert kb_status()["node_count"] == 6

    def test_type_distribution(self, mcp_sandbox):
        origins = kb_status()["origins"]
        assert origins.get("note") == 3
        assert origins.get("webpage") == 2
        assert origins.get("meta") == 1

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
    """Bearer token auth middleware tested against a simple Starlette app."""

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
        """Per-test MCP session."""
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

    def test_tools_list_returns_three(self, http_client, session):
        resp = http_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Mcp-Session-Id": session, **self._ACCEPT},
        )
        tools = _parse_sse_result(resp.text)["tools"]
        names = {t["name"] for t in tools}
        assert names == {"kb_find", "kb_save", "kb_status"}

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

    def test_http_kb_find_search(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_find", {
            "query": "memory", "limit": 5,
        })
        assert isinstance(r, list)
        assert len(r) > 0

    def test_http_kb_find_get(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_find", {
            "id": "test-concept-alpha",
        })
        assert r["title"] == "Test Concept Alpha"

    def test_http_kb_find_list(self, http_client, session):
        r = self._call_tool(http_client, session, "kb_find", {"origin": "note"})
        assert len(r) == 3


# ═══════════════════════════════════════════════════════════════════
# E. End-to-End Workflow Tests
# ═══════════════════════════════════════════════════════════════════

class TestWorkflows:
    """Multi-tool workflows."""

    def test_save_find_cycle(self, mcp_sandbox):
        """Create a page → find via search → retrieve full content."""
        try:
            kb_save(
                title="Workflow Zephyr",
                origin="webpage",
                body="# Zephyr\n\nA unique workflow test page about zephyr.",
                tags=["workflow"],
                sentiment="neutral",
            )
            results = kb_find(query="zephyr", limit=5, mode="bm25")
            assert any(r["node_id"] == "workflow-zephyr" for r in results)

            detail = kb_find(id="workflow-zephyr")
            assert detail["title"] == "Workflow Zephyr"
            assert detail["sentiment"] == "neutral"
        finally:
            _cleanup_added_page("workflow-zephyr")

    def test_list_then_get_all(self, mcp_sandbox):
        """Every listed page must be retrievable."""
        for page in kb_find(origin="note"):
            detail = kb_find(id=page["id"])
            assert detail is not None, f"kb_find(id=) failed for {page['id']}"
            assert detail["title"] == page["title"]
            assert detail["origin"] == page["origin"]

    def test_status_types_match_list(self, mcp_sandbox):
        """Every origin in status must list the reported count."""
        for origin_name, count in kb_status()["origins"].items():
            assert len(kb_find(origin=origin_name)) == count

    def test_save_then_status_increments(self, mcp_sandbox):
        """Adding a page should increase node_count by 1."""
        before = kb_status()["node_count"]
        try:
            kb_save(title="Status Increment Test", origin="webpage", body="Body.")
            assert kb_status()["node_count"] == before + 1
        finally:
            _cleanup_added_page("status-increment-test")
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
            results = kb_find(query=q, limit=3)
            assert isinstance(results, list)

    def test_list_empty_origin(self, mcp_sandbox):
        results = kb_find(origin="nonexistent_origin_xyz")
        assert isinstance(results, list)
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════
# G. Related parameter + auto-suggest
# ═══════════════════════════════════════════════════════════════════

class TestKbSaveRelated:
    """kb_save with the `related` parameter."""

    def test_with_related_frontmatter(self, mcp_sandbox):
        try:
            r = kb_save(
                title="Related Param Test",
                origin="webpage",
                body="# Test\n\nBody about related params.",
                related=["test-concept-alpha", "test-concept-beta"],
            )
            assert "error" not in r
            content = (config.WIKI_DIR / "related-param-test.md").read_text()
            assert "related:" in content
            assert "related: []" not in content
            assert "[[test-concept-alpha]]" in content
            assert "[[test-concept-beta]]" in content
        finally:
            _cleanup_added_page("related-param-test")

    def test_with_related_creates_edges(self, mcp_sandbox):
        try:
            kb_save(
                title="Related Edges Test",
                origin="webpage",
                body="# Test\n\nBody about related edges.",
                related=["test-concept-alpha"],
            )
            conn = get_connection()
            try:
                edges = conn.execute(
                    "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'related'",
                    ("related-edges-test",),
                ).fetchall()
                to_ids = [e["to_id"] for e in edges]
                assert "test-concept-alpha" in to_ids
            finally:
                conn.close()
        finally:
            _cleanup_added_page("related-edges-test")

    def test_without_related_still_empty(self, mcp_sandbox):
        try:
            kb_save(title="No Related Test", origin="webpage", body="Body.")
            content = (config.WIKI_DIR / "no-related-test.md").read_text()
            assert "related: []" in content
        finally:
            _cleanup_added_page("no-related-test")

    def test_returns_suggested_related(self, mcp_sandbox):
        try:
            r = kb_save(
                title="Suggest Test Page",
                origin="webpage",
                body="# Memory\n\nAgent memory systems and retrieval patterns.",
            )
            assert "error" not in r
            assert "suggested_related" in r
            assert isinstance(r["suggested_related"], list)
        finally:
            _cleanup_added_page("suggest-test-page")

    def test_suggested_excludes_declared(self, mcp_sandbox):
        try:
            r = kb_save(
                title="Declared Exclude Test",
                origin="webpage",
                body="# Memory\n\nAgent memory systems for AI agents.",
                related=["test-concept-alpha"],
            )
            assert "error" not in r
            suggested_ids = [s["id"] for s in r.get("suggested_related", [])]
            assert "test-concept-alpha" not in suggested_ids
        finally:
            _cleanup_added_page("declared-exclude-test")

    def test_returns_suggested_tags(self, mcp_sandbox):
        """kb_save returns suggested_tags on create."""
        try:
            r = kb_save(
                title="Tag Suggest Test",
                origin="webpage",
                body="# Memory\n\nAgent memory systems and retrieval.",
            )
            assert "error" not in r
            assert "suggested_tags" in r
            assert isinstance(r["suggested_tags"], list)
        finally:
            _cleanup_added_page("tag-suggest-test")


class TestDetectNewSourcesRelated:
    """detect_new_sources surfaces reverse related edges."""

    def test_reverse_related_surfaced(self, mcp_sandbox):
        from pkb.search import detect_new_sources

        conn = get_connection()
        try:
            candidates = detect_new_sources(conn, "test-concept-alpha")
            candidate_ids = [c.id for c in candidates]
            assert "test-concept-beta" in candidate_ids
        finally:
            conn.close()

    def test_reverse_related_no_duplicates(self, mcp_sandbox):
        from pkb.search import detect_new_sources

        conn = get_connection()
        try:
            candidates = detect_new_sources(conn, "test-concept-alpha")
            candidate_ids = [c.id for c in candidates]
            assert len(candidate_ids) == len(set(candidate_ids))
        finally:
            conn.close()

    def test_reverse_related_already_source_excluded(self, mcp_sandbox):
        from pkb.search import detect_new_sources

        conn = get_connection()
        try:
            candidates = detect_new_sources(conn, "test-concept-alpha")
            candidate_ids = [c.id for c in candidates]
            assert "test-paper-alpha" not in candidate_ids
        finally:
            conn.close()


# ── Temporal / date filter tests ─────────────────────────────────────


class TestKbSavePublishedAt:
    """kb_save with published_at — precision fidelity + validation."""

    def test_save_full_date(self, mcp_sandbox):
        try:
            kb_save(title="Pub Date Day", origin="paper",
                    body="Full date paper.", published_at="2022-08-15")
            fp = config.WIKI_DIR / "pub-date-day.md"
            assert fp.exists()
            assert "published_at: 2022-08-15" in fp.read_text()

            detail = kb_find(id="pub-date-day")
            assert detail["published_at"] == "2022-08-15"
            assert detail["published_relative"] == "Aug 2022" or \
                detail["published_relative"] == "2022"  # depends on today
        finally:
            _cleanup_added_page("pub-date-day")

    def test_save_year_only_precision_preserved(self, mcp_sandbox):
        """A page saved with `published_at: 2022` must read back as '2022', NOT 'Jan 2022'."""
        try:
            kb_save(title="Pub Year Only", origin="paper",
                    body="Year-only pub date.", published_at="2022")
            fp = config.WIKI_DIR / "pub-year-only.md"
            assert "published_at: 2022" in fp.read_text()
            # Make sure we didn't accidentally write a padded form to the file
            assert "published_at: 2022-01-01" not in fp.read_text()

            detail = kb_find(id="pub-year-only")
            assert detail["published_at"] == "2022"
            assert detail["published_relative"] == "2022"
            # Internal columns must not leak via model_dump
            assert "published_at_start" not in detail
            assert "published_at_precision" not in detail
        finally:
            _cleanup_added_page("pub-year-only")

    def test_save_empty_published_at_omits_field(self, mcp_sandbox):
        """Empty string must NOT emit a bare `published_at:` line."""
        try:
            kb_save(title="No Pub Date", origin="note",
                    body="No publication date.", published_at="")
            fp = config.WIKI_DIR / "no-pub-date.md"
            assert "published_at:" not in fp.read_text()
        finally:
            _cleanup_added_page("no-pub-date")

    def test_save_invalid_published_at_raises(self, mcp_sandbox):
        """Garbage published_at must raise — silent drops would let bad data into frontmatter."""
        with pytest.raises(ValueError, match="published_at"):
            kb_save(title="Bad Date", origin="note",
                    body="Bad date.", published_at="August 2022")


class TestKbFindDateFilters:
    """kb_find with created_after / created_before / published_after / published_before."""

    def test_invalid_filter_raises(self, mcp_sandbox):
        """Garbage filter input raises (no silent drops, no shape mismatch)."""
        with pytest.raises(ValueError, match="created_after"):
            kb_find(created_after="last week")

    def test_created_after_filter(self, mcp_sandbox):
        # All fixture pages have created_at: 2026-01-01 — filter after that returns nothing.
        results = kb_find(created_after="2026-12-01", limit=50)
        assert results == []

        # Filter before that returns everything.
        results = kb_find(created_after="2025-01-01", limit=50)
        assert len(results) >= 5

    def test_published_filter_overlap_semantics(self, mcp_sandbox):
        """A year-only `published_at: 2022` row matches published_after='2022-01-01'
        AND does NOT match published_before='2022-01-01' (overlap semantics)."""
        try:
            kb_save(title="Year Paper Filter", origin="paper",
                    body="Year-only.", published_at="2022")

            # Overlap: 2022 interval is [2022-01-01, 2023-01-01)
            in_2022 = kb_find(published_after="2022-01-01",
                              published_before="2023-01-01",
                              limit=50)
            ids = [r["id"] for r in in_2022] if in_2022 else []
            assert "year-paper-filter" in ids

            # _before with the start of the period excludes the row (start is not < start)
            before_2022 = kb_find(published_before="2022-01-01", limit=50)
            before_ids = [r["id"] for r in before_2022] if before_2022 else []
            assert "year-paper-filter" not in before_ids
        finally:
            _cleanup_added_page("year-paper-filter")

    def test_relative_fields_present(self, mcp_sandbox):
        """Every search/browse result carries *_relative computed fields."""
        results = kb_find(origin="note", limit=1)
        assert len(results) >= 1
        r = results[0]
        # updated_relative is always present (updated_at is required on the model)
        assert "updated_relative" in r

    def test_what_did_i_add_last_week(self, mcp_sandbox):
        """End-to-end: the 'what did I add to my KB in the last week?' use case.

        Mirrors the canonical question that surfaced the dispatch bug in the
        live Claude.ai session: it requires bare browse mode (no query, no
        origin/tag filter), a created_after filter relative to today, sort
        by created_at, and relative-time rendering. All in one call.
        """
        from datetime import date, timedelta

        try:
            # Create a brand-new page; kb_save stamps created_at = today.
            kb_save(title="Brand New Page", origin="note",
                    body="Something added recently.", tags=["test"])

            today = date.today()
            last_week = (today - timedelta(days=7)).isoformat()

            # Exactly the call shape "what did I add last week?" should produce:
            # no id, no query, no origin/tag — just a date filter + sort.
            results = kb_find(created_after=last_week, sort="created_at", limit=20)

            assert isinstance(results, list), \
                f"Expected list, got {type(results).__name__}: {results!r}"

            ids = [r["id"] for r in results]
            assert "brand-new-page" in ids, \
                f"Just-created page should appear in 'last week' query; got {ids}"

            # All results must respect the filter — no page added before last_week.
            for r in results:
                assert r["created_at"] >= last_week, (
                    f"Filter leak: {r['id']} has created_at={r['created_at']}, "
                    f"before cutoff {last_week}"
                )

            # Sorted by created_at descending so the most-recent appears first.
            cdates = [r["created_at"] for r in results]
            assert cdates == sorted(cdates, reverse=True), \
                f"Results not sorted by created_at desc: {cdates}"

            # The brand-new page renders with a recent relative-time label.
            new = next(r for r in results if r["id"] == "brand-new-page")
            assert new["created_relative"] in ("today", "yesterday"), \
                f"created_relative should be today/yesterday, got {new.get('created_relative')!r}"
            # The LLM should prefer the relative form in chat output, but raw is also there.
            assert new["created_at"] == today.isoformat()
        finally:
            _cleanup_added_page("brand-new-page")


class TestLegacyBriefingDateFallback:
    """The indexer reads `briefing_date` as a fallback for `published_at`."""

    def test_legacy_fallback_populates_published_at(self, mcp_sandbox):
        """A page with only briefing_date should expose published_at via the DB column."""
        # Write a legacy-style page to the sandbox and index it directly.
        # (kb_save reindex mode needs the page already in the DB.)
        legacy_path = config.WIKI_DIR / "legacy-briefing-fallback.md"
        legacy_path.write_text(textwrap.dedent("""\
            ---
            title: Legacy Briefing Fallback Test
            origin: webpage
            ingested_via: notion_briefing
            briefing_date: 2026-03-28
            related: []
            sources: []
            created_at: 2026-03-28
            updated_at: 2026-03-28
            ---

            # Legacy Briefing

            Body.
            """))
        try:
            conn = get_connection()
            try:
                provider = get_provider("noop")
                indexer = Indexer(conn, embedding_provider=provider)
                indexer.index_single(legacy_path)
            finally:
                conn.close()

            detail = kb_find(id="legacy-briefing-fallback")
            # published_at column should be populated from briefing_date
            assert detail is not None
            assert detail["published_at"] == "2026-03-28"
            # Computed relative field also follows
            assert detail["published_relative"] is not None
        finally:
            _cleanup_added_page("legacy-briefing-fallback")


class TestVecDateFilterFallback:
    """Vec mode + restrictive date filter works under the over-fetch fallback path.

    PKB_VEC_FORCE_OVERFETCH=1 currently has no separate code path (over-fetch is the
    only implementation), but the env var is reserved for the prefilter path coming
    later. This test exercises the post-filter logic regardless.
    """

    def test_vec_filter_returns_only_matching(self, mcp_sandbox, monkeypatch):
        monkeypatch.setenv("PKB_VEC_FORCE_OVERFETCH", "1")
        # Fixture: all 6 fixture pages have created_at: 2026-01-01 or 2026-02-01
        # Restrict to created_after 2026-03-01: zero results expected.
        results = kb_find(query="memory", mode="hybrid",
                          created_after="2026-03-01", limit=10)
        assert results == []

        # Restrict to created_after 2025-12-01: all relevant pages returned.
        results = kb_find(query="memory", mode="hybrid",
                          created_after="2025-12-01", limit=10)
        assert len(results) >= 1
