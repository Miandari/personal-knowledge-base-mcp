"""Paths, DB location, embedding model, dimension."""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
VAULT_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = VAULT_ROOT / "wiki"
RAW_DIR = VAULT_ROOT / ".raw"
DB_PATH = VAULT_ROOT / "kb.db"

# ── Embedding ──────────────────────────────────────────────────────────
EMBEDDING_PROVIDER = "voyage"       # "voyage" | "noop"
EMBEDDING_MODEL = "voyage-3.5"
EMBEDDING_DIMENSIONS = 1024
CHUNK_TARGET_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 100
VOYAGE_BATCH_SIZE = 128

# ── Indexer ────────────────────────────────────────────────────────────
# Files to skip during indexing (relative to wiki/)
SKIP_FILES = {"hot.md", ".gitkeep"}

# Node IDs of structural/navigation pages to demote in search results.
# These pages are indexed (for kb_get) but deprioritized in search ranking.
META_NODE_IDS = {"index", "log"}
