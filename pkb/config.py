"""Paths, DB location, embedding model, dimension."""

import os
from pathlib import Path


# ── Vault discovery ───────────────────────────────────────────────────
# Priority: set_vault_root() (CLI --vault) > PKB_VAULT_ROOT env > cwd

_vault_root_override: Path | None = None


def set_vault_root(path: Path) -> None:
    """Set vault root explicitly (called by CLI --vault arg)."""
    global _vault_root_override, VAULT_ROOT, WIKI_DIR, RAW_DIR, DB_PATH
    _vault_root_override = path.resolve()
    VAULT_ROOT = _vault_root_override
    WIKI_DIR = VAULT_ROOT / "wiki"
    RAW_DIR = VAULT_ROOT / ".raw"
    DB_PATH = VAULT_ROOT / "pkb.db"


def _discover_vault_root() -> Path:
    """CLI arg (already set via set_vault_root) > env var > cwd."""
    if _vault_root_override:
        return _vault_root_override
    if env := os.getenv("PKB_VAULT_ROOT"):
        return Path(env).resolve()
    return Path.cwd()


VAULT_ROOT = _discover_vault_root()
WIKI_DIR = VAULT_ROOT / "wiki"
RAW_DIR = VAULT_ROOT / ".raw"
DB_PATH = VAULT_ROOT / "pkb.db"

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
