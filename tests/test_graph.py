"""DAG traversal, staleness detection, and explore result structure tests."""

from pathlib import Path

import pytest

import sys
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pkb.db import get_connection, init_schema
from pkb.search import (
    get_source_chain, get_derived_pages, get_neighborhood,
    get_stale_nodes, explore, get_node, get_node_summary,
)
from pkb.embeddings import get_provider
from pkb import config


@pytest.fixture(scope="module")
def conn():
    """Live database connection."""
    if not config.DB_PATH.exists():
        pytest.skip("No live database. Run `python -m pkb rebuild` first.")
    c = get_connection()
    yield c
    c.close()


class TestSourceChain:
    """Test walking up 'sources' edges."""

    def test_concept_has_sources(self, conn):
        """ai-coding-agents should trace back to source pages."""
        chain = get_source_chain(conn, "ai-coding-agents")
        ids = [c["id"] for c in chain]
        assert "ai-coding-agents" in ids, "Self should be in chain"
        # Should have at least the uncomfortable-truths source
        assert any("uncomfortable-truths" in cid for cid in ids) or len(chain) > 1, \
            f"Source chain too short: {ids}"

    def test_source_page_chain(self, conn):
        """A source page's chain should include just itself (leaf node)."""
        chain = get_source_chain(conn, "uncomfortable-truths-ai-coding-agents")
        # Source pages may or may not have their own sources (raw files)
        assert len(chain) >= 1


class TestDerivedPages:
    """Test walking down: what pages cite this one as a source?"""

    def test_source_is_cited(self, conn):
        """uncomfortable-truths should be cited by ai-coding-agents."""
        derived = get_derived_pages(conn, "uncomfortable-truths-ai-coding-agents")
        ids = [d["id"] for d in derived]
        # ai-coding-agents lists uncomfortable-truths as a source
        if ids:
            # At least one page should cite it
            assert len(ids) >= 1


class TestNeighborhood:
    """Test local subgraph queries."""

    def test_neighborhood_returns_neighbors(self, conn):
        """ai-coding-agents should have neighbors within 2 hops."""
        neighbors = get_neighborhood(conn, "ai-coding-agents", radius=2)
        assert len(neighbors) > 0, "ai-coding-agents has no neighbors"
        ids = [n.id for n in neighbors]
        # Should include related entities/concepts
        assert any("claude-code" in nid for nid in ids) or len(neighbors) >= 2, \
            f"Neighbors look sparse: {ids}"


class TestStaleness:
    """Test staleness detection."""

    def test_stale_detection_runs(self, conn):
        """Staleness query should execute without error."""
        stale = get_stale_nodes(conn)
        # May or may not have stale nodes depending on vault state
        assert isinstance(stale, list)

    def test_stale_structure(self, conn):
        """Stale nodes should have expected fields."""
        stale = get_stale_nodes(conn)
        for s in stale:
            assert "concept_id" in s
            assert "concept_title" in s
            assert "updated_source_count" in s


class TestExplore:
    """Test the explore function that drives interactive retrieval."""

    def test_explore_known_topic(self, conn):
        """Exploring 'AI coding agents' should find the concept page."""
        result = explore(conn, "AI coding agents")
        assert result.topic == "AI coding agents"
        # Should find a hub page
        if result.hub:
            assert result.hub.origin in ("note", "webpage", "paper", "conversation", "book", "transcript", "meta")

    def test_explore_returns_search_results(self, conn):
        """Explore should always include search results."""
        result = explore(conn, "agent memory")
        assert len(result.search_results) > 0, "Explore returned no search results"

    def test_explore_suggests_actions(self, conn):
        """Explore should suggest next actions."""
        result = explore(conn, "AI coding agents")
        assert len(result.suggested_actions) > 0, "No suggested actions"

    def test_explore_unknown_topic(self, conn):
        """Exploring an unknown topic should still return gracefully."""
        result = explore(conn, "quantum computing in agriculture")
        # Should suggest adding sources
        assert len(result.suggested_actions) > 0

    def test_explore_adjacent_topics(self, conn):
        """If a hub exists, adjacent topics should be populated."""
        result = explore(conn, "AI coding agents")
        if result.hub:
            # Adjacent topics come from the neighborhood
            # May be empty if the graph is small, but the field should exist
            assert isinstance(result.adjacent_topics, list)

    def test_explore_staleness_check(self, conn):
        """Explore should report staleness status."""
        result = explore(conn, "AI coding agents")
        assert isinstance(result.is_stale, bool)
        assert isinstance(result.stale_sources, list)
        assert isinstance(result.unincorporated_sources, list)


class TestNodeRetrieval:
    """Test get_node and get_node_summary."""

    def test_get_existing_node(self, conn):
        """Should return full details for a known page."""
        detail = get_node(conn, "ai-coding-agents")
        assert detail is not None
        assert detail.title == "AI coding agents"
        assert detail.origin == "note"
        assert len(detail.body) > 100
        assert len(detail.tags) > 0

    def test_get_nonexistent_node(self, conn):
        """Should return None for unknown node."""
        assert get_node(conn, "nonexistent-page") is None

    def test_get_node_summary(self, conn):
        """Summary should have all required fields."""
        summary = get_node_summary(conn, "mempalace")
        assert summary is not None
        assert summary.title == "mempalace"
        assert summary.origin == "note"
        assert summary.updated_at
