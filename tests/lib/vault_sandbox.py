"""Vault sandbox for tests that write files.

Copies the vault to a temp dir, builds a scoped SQLite index.
"""

import shutil
import tempfile
from pathlib import Path

import sys
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pkb.db import get_connection, init_schema
from pkb.indexer import Indexer
from pkb.embeddings import NoopEmbedding
from pkb.search import hybrid_search, fts_search


class VaultSandbox:
    """A temporary copy of the vault for safe testing.

    Usage:
        with VaultSandbox(source_vault) as sb:
            sb.write_raw("articles/test.md", content)
            results = sb.kb_search("test query")
    """

    def __init__(self, source_vault: str | Path):
        self.source = Path(source_vault)
        self.tmpdir = None
        self.vault_path = None
        self._conn = None
        self._db_path = None

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="kb_test_")
        self.vault_path = Path(self.tmpdir) / "vault"

        # Copy wiki/ and .raw/ -- skip .git, .obsidian, heavy dirs
        shutil.copytree(
            self.source,
            self.vault_path,
            ignore=shutil.ignore_patterns(".git", ".obsidian", "node_modules", ".qmd", "pkb.db*"),
        )

        # Create a sandbox SQLite database
        self._db_path = Path(self.tmpdir) / "sandbox.db"
        self._conn = get_connection(self._db_path)
        init_schema(self._conn)

        # Index the sandbox wiki with noop embeddings
        provider = NoopEmbedding()
        indexer = Indexer(self._conn, wiki_dir=self.vault_path / "wiki", embedding_provider=provider)
        indexer.rebuild()

        return self

    def __exit__(self, *exc):
        if self._conn:
            self._conn.close()
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_raw(self, subpath: str, content: str):
        """Write a file under .raw/ in the sandbox vault."""
        target = self.vault_path / ".raw" / subpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def write_wiki(self, subpath: str, content: str):
        """Write a file under wiki/ in the sandbox vault."""
        target = self.vault_path / "wiki" / subpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def read_wiki(self, subpath: str) -> str:
        """Read a file from wiki/ in the sandbox vault."""
        return (self.vault_path / "wiki" / subpath).read_text()

    def wiki_exists(self, subpath: str) -> bool:
        """Check if a wiki page exists in the sandbox."""
        return (self.vault_path / "wiki" / subpath).exists()

    def list_wiki(self, pattern: str = "**/*.md") -> list[str]:
        """List wiki pages matching a glob pattern."""
        return [str(p.relative_to(self.vault_path / "wiki"))
                for p in (self.vault_path / "wiki").glob(pattern)]

    def reindex(self):
        """Re-index the sandbox after writing new files."""
        provider = NoopEmbedding()
        indexer = Indexer(self._conn, wiki_dir=self.vault_path / "wiki", embedding_provider=provider)
        indexer.rebuild(force=True)

    def kb_search(self, query: str, n: int = 10) -> list[dict]:
        """Search the sandbox's index."""
        results = fts_search(self._conn, query, limit=n)
        return [r.model_dump() for r in results]
