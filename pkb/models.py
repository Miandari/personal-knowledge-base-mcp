"""Pydantic models for search results, exploration, and node summaries."""

from pydantic import BaseModel, Field, computed_field

from .dates import relative_time


class _DatedModel(BaseModel):
    """Mixin-like base providing date fields + precision-aware relative renders.

    `published_at_start` and `published_at_precision` are internal-only —
    `exclude=True` keeps them out of `model_dump()` so MCP responses stay clean.
    The computed `*_relative` fields are what callers see.
    """

    created_at: str | None = None
    updated_at: str
    published_at: str | None = None
    published_at_start: str | None = Field(default=None, exclude=True)
    published_at_precision: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def created_relative(self) -> str | None:
        return relative_time(self.created_at, "day")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def updated_relative(self) -> str | None:
        return relative_time(self.updated_at, "day")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def published_relative(self) -> str | None:
        return relative_time(self.published_at_start, self.published_at_precision)


class NodeSummary(_DatedModel):
    """Lightweight node reference used in lists and edges."""
    id: str
    title: str
    origin: str
    file_path: str = ""
    snippet: str = ""


class SearchResult(_DatedModel):
    """A single hybrid search result."""
    node_id: str
    title: str
    origin: str
    score: float              # raw RRF score (do NOT normalize)
    vec_distance: float | None = None  # raw cosine distance from best chunk
    snippet: str = ""


class NodeDetail(_DatedModel):
    """Full page content + metadata + edges."""
    id: str
    file_path: str
    title: str
    origin: str
    created_at: str  # required for detail view (override parent's optional)
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
