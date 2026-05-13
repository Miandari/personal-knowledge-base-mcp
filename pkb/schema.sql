-- compiled-knowledge-base SQLite schema
-- Markdown files are source of truth; this DB is derived + rebuildable.

-- ═══════════════════════════════════════════════════════════════
-- NODES: one row per markdown page
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS nodes (
    id            TEXT PRIMARY KEY,    -- slug: "agent-memory"
    file_path     TEXT NOT NULL UNIQUE,-- "wiki/agent-memory.md"
    title         TEXT NOT NULL,
    origin        TEXT NOT NULL,       -- webpage|paper|conversation|note|book|transcript|meta
    created_at    TEXT NOT NULL,       -- YYYY-MM-DD
    updated_at    TEXT NOT NULL,
    -- Denormalized filterable fields
    sentiment     TEXT,
    complexity    TEXT,
    confidence    TEXT,
    ingested_via  TEXT,
    -- Publication date (source's own date, distinct from created_at).
    -- Supports partial precision (year / year-month / year-month-day).
    -- `published_at` stores the raw form for display; `_start`/`_end`
    -- bracket a half-open interval for filtering; `_precision` lets
    -- the renderer be honest about what the user actually wrote.
    published_at           TEXT,
    published_at_start     TEXT,  -- YYYY-MM-DD, inclusive
    published_at_end       TEXT,  -- YYYY-MM-DD, exclusive
    published_at_precision TEXT,  -- 'year' | 'month' | 'day'
    url           TEXT,
    author        TEXT,
    -- Full content
    body          TEXT NOT NULL,       -- markdown body (no frontmatter)
    word_count    INTEGER,
    -- Sync metadata
    file_hash     TEXT,               -- MD5 of file on disk, for change detection
    indexed_at    TEXT                 -- ISO timestamp of last sync
);

-- ═══════════════════════════════════════════════════════════════
-- EDGES: directional links between nodes (the DAG)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS edges (
    from_id   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    to_id     TEXT NOT NULL,  -- may reference unindexed node (dangling OK)
    edge_type TEXT NOT NULL,  -- 'source', 'related', 'link'
    PRIMARY KEY (from_id, to_id, edge_type)
);

-- ═══════════════════════════════════════════════════════════════
-- TAGS + ALIASES
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS tags (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (node_id, tag)
);

CREATE TABLE IF NOT EXISTS aliases (
    alias_norm TEXT PRIMARY KEY,    -- normalized: "concepts/agent-memory" or "agent-memory"
    alias      TEXT NOT NULL,       -- original form: "Agent Memory", "concepts/agent-memory"
    node_id    TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    alias_kind TEXT,                -- 'title', 'old_path', 'manual', 'former_slug'
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_aliases_node ON aliases(node_id);

-- ═══════════════════════════════════════════════════════════════
-- CHUNKS: sub-page segments for embedding granularity
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id      TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    text         TEXT NOT NULL,
    start_line   INTEGER,
    end_line     INTEGER,
    content_hash TEXT,
    UNIQUE (node_id, chunk_index)
);

-- ═══════════════════════════════════════════════════════════════
-- FTS5: full-text search index (BM25)
-- ═══════════════════════════════════════════════════════════════
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id UNINDEXED,
    title,
    body,
    tags_text,
    tokenize='unicode61'
);

-- ═══════════════════════════════════════════════════════════════
-- VECTOR: chunk-level embeddings (sqlite-vec)
-- ═══════════════════════════════════════════════════════════════
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
    embedding float[1024]
);

-- ═══════════════════════════════════════════════════════════════
-- EMBEDDING CACHE
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT NOT NULL,
    model        TEXT NOT NULL,
    embedding    BLOB NOT NULL,
    dimensions   INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (content_hash, model)
);

-- ═══════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_edges_to              ON edges(to_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_from            ON edges(from_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_nodes_origin          ON nodes(origin);
CREATE INDEX IF NOT EXISTS idx_nodes_created         ON nodes(created_at);
CREATE INDEX IF NOT EXISTS idx_nodes_updated         ON nodes(updated_at);
CREATE INDEX IF NOT EXISTS idx_nodes_published_start ON nodes(published_at_start);
CREATE INDEX IF NOT EXISTS idx_nodes_published_end   ON nodes(published_at_end);
CREATE INDEX IF NOT EXISTS idx_chunks_node           ON chunks(node_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag              ON tags(tag);

-- ═══════════════════════════════════════════════════════════════
-- VIRTUAL TABLE CLEANUP TRIGGER
-- ═══════════════════════════════════════════════════════════════
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_vec WHERE rowid = OLD.chunk_id;
END;
