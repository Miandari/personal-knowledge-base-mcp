-- compiled-knowledge-base SQLite schema
-- Markdown files are source of truth; this DB is derived + rebuildable.

-- ═══════════════════════════════════════════════════════════════
-- NODES: one row per markdown page
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS nodes (
    id            TEXT PRIMARY KEY,    -- slug: "concepts/ai-coding-agents"
    file_path     TEXT NOT NULL UNIQUE,-- "wiki/concepts/ai-coding-agents.md"
    title         TEXT NOT NULL,
    type          TEXT NOT NULL,       -- source|entity|concept|domain|comparison|question|overview|meta
    status        TEXT NOT NULL DEFAULT 'seed',
    created       TEXT NOT NULL,       -- YYYY-MM-DD
    updated       TEXT NOT NULL,
    -- Denormalized filterable fields
    sentiment     TEXT,
    source_type   TEXT,
    entity_type   TEXT,
    complexity    TEXT,
    confidence    TEXT,
    ingested_via  TEXT,
    briefing_date TEXT,
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
    edge_type TEXT NOT NULL,
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
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (node_id, alias)
);

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
CREATE INDEX IF NOT EXISTS idx_edges_to       ON edges(to_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_from     ON edges(from_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_nodes_type     ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_updated  ON nodes(updated);
CREATE INDEX IF NOT EXISTS idx_nodes_status   ON nodes(status);
CREATE INDEX IF NOT EXISTS idx_chunks_node    ON chunks(node_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag       ON tags(tag);

-- ═══════════════════════════════════════════════════════════════
-- VIRTUAL TABLE CLEANUP TRIGGER
-- ═══════════════════════════════════════════════════════════════
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_vec WHERE rowid = OLD.chunk_id;
END;
