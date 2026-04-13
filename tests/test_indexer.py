"""Index builder correctness tests.

Tests that the indexer correctly parses markdown, populates SQLite
tables, handles hash-based skip, orphan cleanup, and FTS5 population.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pkb.db import get_connection, init_schema, reset_db
from pkb.indexer import (
    Indexer, parse_markdown, file_md5, slug_from_path,
    extract_wikilinks, resolve_wikilink, chunk_body,
)
from pkb.embeddings import NoopEmbedding
from pkb import config


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def live_db():
    """Use the live vault database (requires `python -m pkb rebuild`)."""
    if not config.DB_PATH.exists():
        pytest.skip("No live database. Run `python -m pkb rebuild` first.")
    conn = get_connection()
    yield conn
    conn.close()


class TestMarkdownParsing:
    """Test frontmatter + body extraction."""

    def test_parse_with_frontmatter(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("---\ntype: concept\ntitle: Test\n---\n\n# Test\n\nBody here.")
        fm, body = parse_markdown(f)
        assert fm["type"] == "concept"
        assert fm["title"] == "Test"
        assert "Body here" in body

    def test_parse_without_frontmatter(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Just a heading\n\nNo frontmatter.")
        fm, body = parse_markdown(f)
        assert fm == {}
        assert "Just a heading" in body

    def test_parse_complex_frontmatter(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(
            '---\ntype: source\ntitle: "Complex Title"\ntags:\n  - tag1\n  - tag2\n'
            'sources:\n  - "[[some-source]]"\nsentiment: critical\n---\n\nBody.'
        )
        fm, body = parse_markdown(f)
        assert fm["sentiment"] == "critical"
        assert fm["tags"] == ["tag1", "tag2"]
        assert len(fm["sources"]) == 1


class TestWikilinkExtraction:
    """Test wikilink parsing."""

    def test_basic_wikilinks(self):
        body = "See [[ai-coding-agents]] and [[claude-code]] for details."
        links = extract_wikilinks(body)
        assert "ai-coding-agents" in links
        assert "claude-code" in links

    def test_display_text_wikilinks(self):
        body = "See [[ai-coding-agents|AI coding agents]] for details."
        links = extract_wikilinks(body)
        assert "ai-coding-agents" in links
        assert len(links) == 1

    def test_no_wikilinks(self):
        assert extract_wikilinks("Plain text with no links.") == []

    def test_raw_file_references(self):
        """Wikilinks to .raw/ files should be extracted (resolution handles them)."""
        body = "Source: [[.raw/notion/2026-03-28.md]]"
        links = extract_wikilinks(body)
        assert ".raw/notion/2026-03-28.md" in links


class TestWikilinkResolution:
    """Test wikilink → node ID resolution."""

    def test_exact_match(self):
        table = {"concepts/ai-coding-agents": ["concepts/ai-coding-agents"]}
        assert resolve_wikilink("concepts/ai-coding-agents", table) == "concepts/ai-coding-agents"

    def test_slug_suffix_match(self):
        table = {"concepts/ai-coding-agents": ["concepts/ai-coding-agents"]}
        assert resolve_wikilink("ai-coding-agents", table) == "concepts/ai-coding-agents"

    def test_case_insensitive(self):
        table = {"concepts/ai-coding-agents": ["concepts/ai-coding-agents"]}
        assert resolve_wikilink("AI-Coding-Agents", table) == "concepts/ai-coding-agents"

    def test_unresolved(self):
        table = {"concepts/ai-coding-agents": ["concepts/ai-coding-agents"]}
        assert resolve_wikilink("nonexistent-page", table) is None

    def test_raw_file_skipped(self):
        table = {"concepts/ai-coding-agents": ["concepts/ai-coding-agents"]}
        assert resolve_wikilink(".raw/notion/2026-03-28.md", table) is None

    def test_ambiguous_alias(self):
        table = {"agent": ["concepts/ai-agent", "entities/agent-framework"]}
        assert resolve_wikilink("agent", table) is None


class TestChunking:
    """Test body chunking for embedding."""

    def test_short_body_single_chunk(self):
        chunks = chunk_body("Short body text.", title="Test", tags=["tag1"])
        assert len(chunks) == 1
        assert "Title: Test" in chunks[0]["text"]
        assert "Short body text." in chunks[0]["text"]

    def test_heading_based_splitting(self):
        body = "Intro paragraph.\n\n## Section 1\n\nContent 1.\n\n## Section 2\n\nContent 2."
        chunks = chunk_body(body, title="Test", target_tokens=20)
        assert len(chunks) >= 2

    def test_empty_body(self):
        chunks = chunk_body("", title="Test")
        assert len(chunks) == 1
        assert "Title: Test" in chunks[0]["text"]

    def test_chunk_indices_sequential(self):
        body = "## A\n\nText A.\n\n## B\n\nText B.\n\n## C\n\nText C."
        chunks = chunk_body(body, title="Test", target_tokens=10)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))


class TestSlugFromPath:
    """Test path → slug conversion."""

    def test_concept_path(self):
        wiki = Path("/vault/wiki")
        fp = Path("/vault/wiki/concepts/ai-coding-agents.md")
        assert slug_from_path(fp, wiki) == "concepts/ai-coding-agents"

    def test_nested_path(self):
        wiki = Path("/vault/wiki")
        fp = Path("/vault/wiki/meta/tag-registry.md")
        assert slug_from_path(fp, wiki) == "meta/tag-registry"


class TestIndexerLiveVault:
    """Tests against the live vault's existing pages."""

    def test_correct_node_count(self, live_db):
        """All wiki pages should be indexed."""
        count = live_db.execute("SELECT COUNT(*) as cnt FROM nodes").fetchone()["cnt"]
        # 14 pages: 5 concepts + 4 entities + 1 source + index + log + 1 question + meta (varies)
        # At minimum we should have the 11 main content pages
        assert count >= 11, f"Expected ≥11 nodes, got {count}"

    def test_edge_extraction(self, live_db):
        """Edges should exist for pages with sources/related."""
        edges = live_db.execute("SELECT COUNT(*) as cnt FROM edges").fetchone()["cnt"]
        assert edges > 0, "No edges found"

        # ai-coding-agents has sources AND related
        ai_edges = live_db.execute(
            "SELECT edge_type, COUNT(*) as cnt FROM edges WHERE from_id = 'concepts/ai-coding-agents' GROUP BY edge_type"
        ).fetchall()
        edge_types = {r["edge_type"]: r["cnt"] for r in ai_edges}
        assert "related" in edge_types or "wikilink" in edge_types, f"ai-coding-agents has no related/wikilink edges: {edge_types}"

    def test_tag_extraction(self, live_db):
        """Tags should be populated from frontmatter."""
        tag_count = live_db.execute("SELECT COUNT(*) as cnt FROM tags").fetchone()["cnt"]
        assert tag_count > 0, "No tags found"

        # uncomfortable-truths should have 'ai-coding-agents' tag
        has_tag = live_db.execute(
            "SELECT 1 FROM tags WHERE node_id = 'sources/uncomfortable-truths-ai-coding-agents' AND tag = 'ai-coding-agents'"
        ).fetchone()
        assert has_tag, "uncomfortable-truths missing 'ai-coding-agents' tag"

    def test_chunk_generation(self, live_db):
        """Every node should have at least one chunk."""
        nodes_without_chunks = live_db.execute("""
            SELECT n.id FROM nodes n
            LEFT JOIN chunks c ON c.node_id = n.id
            WHERE c.chunk_id IS NULL
        """).fetchall()
        orphan_ids = [r["id"] for r in nodes_without_chunks]
        assert not orphan_ids, f"Nodes without chunks: {orphan_ids}"

    def test_fts5_population(self, live_db):
        """FTS5 should have entries for all nodes."""
        fts_count = live_db.execute("SELECT COUNT(*) as cnt FROM nodes_fts").fetchone()["cnt"]
        node_count = live_db.execute("SELECT COUNT(*) as cnt FROM nodes").fetchone()["cnt"]
        assert fts_count == node_count, f"FTS5 has {fts_count} entries, nodes has {node_count}"

    def test_fts5_searchable(self, live_db):
        """FTS5 should return results for known content."""
        results = live_db.execute(
            "SELECT node_id FROM nodes_fts WHERE nodes_fts MATCH '\"AI\" OR \"coding\" OR \"agents\"' LIMIT 5"
        ).fetchall()
        assert len(results) > 0, "FTS5 returned no results for 'AI coding agents'"

    def test_hash_based_skip(self, live_db):
        """Nodes should have file_hash set after successful indexing."""
        no_hash = live_db.execute(
            "SELECT id FROM nodes WHERE file_hash IS NULL"
        ).fetchall()
        # Some nodes might have NULL hash if embedding failed, but most should have it
        no_hash_ids = [r["id"] for r in no_hash]
        assert len(no_hash_ids) <= 2, f"Too many nodes without file_hash: {no_hash_ids}"


class TestIndexerSandbox:
    """Tests using a temporary database and fake wiki pages."""

    def test_index_single_page(self, tmp_db, tmp_path):
        wiki_dir = tmp_path / "wiki" / "concepts"
        wiki_dir.mkdir(parents=True)
        page = wiki_dir / "test-concept.md"
        page.write_text(
            "---\ntype: concept\ntitle: Test Concept\ncreated: 2026-04-12\n"
            "updated: 2026-04-12\nstatus: seed\ntags:\n  - test\n---\n\n"
            "# Test Concept\n\nSome content about testing."
        )

        provider = NoopEmbedding()
        indexer = Indexer(tmp_db, wiki_dir=tmp_path / "wiki", embedding_provider=provider)
        stats = indexer.rebuild()

        assert stats["files_indexed"] == 1
        node = tmp_db.execute("SELECT * FROM nodes WHERE id = 'concepts/test-concept'").fetchone()
        assert node is not None
        assert node["title"] == "Test Concept"
        assert node["type"] == "concept"

    def test_incremental_skip(self, tmp_db, tmp_path):
        wiki_dir = tmp_path / "wiki" / "concepts"
        wiki_dir.mkdir(parents=True)
        page = wiki_dir / "test.md"
        page.write_text("---\ntype: concept\ntitle: Test\ncreated: 2026-04-12\nupdated: 2026-04-12\nstatus: seed\n---\n\nBody.")

        provider = NoopEmbedding()
        indexer = Indexer(tmp_db, wiki_dir=tmp_path / "wiki", embedding_provider=provider)

        # First run
        stats1 = indexer.rebuild()
        assert stats1["files_indexed"] == 1

        # Second run — same file, should skip
        indexer2 = Indexer(tmp_db, wiki_dir=tmp_path / "wiki", embedding_provider=provider)
        stats2 = indexer2.rebuild()
        assert stats2["files_skipped"] == 1
        assert stats2["files_indexed"] == 0

    def test_orphan_cleanup(self, tmp_db, tmp_path):
        wiki_dir = tmp_path / "wiki" / "concepts"
        wiki_dir.mkdir(parents=True)
        page = wiki_dir / "to-delete.md"
        page.write_text("---\ntype: concept\ntitle: Delete Me\ncreated: 2026-04-12\nupdated: 2026-04-12\nstatus: seed\n---\n\nBody.")

        provider = NoopEmbedding()
        indexer = Indexer(tmp_db, wiki_dir=tmp_path / "wiki", embedding_provider=provider)
        indexer.rebuild()

        # Verify it's indexed
        assert tmp_db.execute("SELECT 1 FROM nodes WHERE id = 'concepts/to-delete'").fetchone()

        # Delete the file and re-index
        page.unlink()
        indexer2 = Indexer(tmp_db, wiki_dir=tmp_path / "wiki", embedding_provider=provider)
        stats = indexer2.rebuild()
        assert stats["files_deleted"] == 1

        # Node should be gone
        assert tmp_db.execute("SELECT 1 FROM nodes WHERE id = 'concepts/to-delete'").fetchone() is None

    def test_dry_run(self, tmp_db, tmp_path):
        wiki_dir = tmp_path / "wiki" / "concepts"
        wiki_dir.mkdir(parents=True)
        page = wiki_dir / "test.md"
        page.write_text("---\ntype: concept\ntitle: Test\ncreated: 2026-04-12\nupdated: 2026-04-12\nstatus: seed\n---\n\nBody.")

        indexer = Indexer(tmp_db, wiki_dir=tmp_path / "wiki", dry_run=True)
        stats = indexer.rebuild()

        assert stats["files_indexed"] == 1
        # But no actual data in DB
        count = tmp_db.execute("SELECT COUNT(*) as cnt FROM nodes").fetchone()["cnt"]
        assert count == 0, f"Dry run should not write to DB, got {count} nodes"
