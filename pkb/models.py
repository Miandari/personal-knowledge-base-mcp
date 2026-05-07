"""Pydantic models for search results, exploration, and node summaries."""

from pydantic import BaseModel


class NodeSummary(BaseModel):
    """Lightweight node reference used in lists and edges."""
    id: str
    title: str
    origin: str
    status: str
    updated_at: str
    file_path: str = ""
    snippet: str = ""


class SearchResult(BaseModel):
    """A single hybrid search result."""
    node_id: str
    title: str
    origin: str
    status: str
    updated_at: str
    score: float              # raw RRF score (do NOT normalize)
    vec_distance: float | None = None  # raw cosine distance from best chunk
    snippet: str = ""


class NodeDetail(BaseModel):
    """Full page content + metadata + edges."""
    id: str
    file_path: str
    title: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    body: str
    word_count: int = 0
    tags: list[str] = []
    aliases: list[str] = []
    sentiment: str | None = None
    url: str | None = None
    author: str | None = None
    # Edges
    sources: list[NodeSummary] = []
    sourced_by: list[NodeSummary] = []
    related: list[NodeSummary] = []
    wikilinks_out: list[str] = []


class ExploreResult(BaseModel):
    """Structured exploration state (System 2 — reflection-time use)."""
    topic: str

    # Hub page for this topic (page with outgoing source edges)
    hub: NodeSummary | None = None

    # Staleness assessment
    is_stale: bool = False
    stale_sources: list[NodeSummary] = []        # existing sources updated after hub
    unincorporated_sources: list[NodeSummary] = []  # new related pages not in sources
    days_since_update: int | None = None

    # Graph context
    source_chain: list[NodeSummary] = []
    derived_pages: list[NodeSummary] = []
    adjacent_topics: list[NodeSummary] = []

    # Search context (when no exact hub exists)
    search_results: list[SearchResult] = []

    # Suggested next actions
    suggested_actions: list[str] = []


class StatusResult(BaseModel):
    """Index health summary."""
    node_count: int = 0
    edge_count: int = 0
    chunk_count: int = 0
    embedded_chunks: int = 0
    embedding_coverage: float = 0.0
    stale_count: int = 0
    orphan_chunks: int = 0
    origins: dict[str, int] = {}
