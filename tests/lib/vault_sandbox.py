"""Vault sandbox for tests that write files.

Copies the vault to a temp dir and provides a scoped qmd collection.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class VaultSandbox:
    """A temporary copy of the vault for safe testing.

    Usage:
        with VaultSandbox(source_vault) as sb:
            sb.write_raw("articles/test.md", content)
            results = sb.qmd_query("test query")
    """

    def __init__(self, source_vault: str | Path):
        self.source = Path(source_vault)
        self.tmpdir = None
        self.vault_path = None
        self.collection_name = "kb_test"

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="kb_test_")
        self.vault_path = Path(self.tmpdir) / "vault"

        # Copy wiki/ and .raw/ — skip .git, .obsidian, heavy dirs
        shutil.copytree(
            self.source,
            self.vault_path,
            ignore=shutil.ignore_patterns(".git", ".obsidian", "node_modules", ".qmd"),
        )

        # Register a temp qmd collection pointing at the sandbox wiki/
        subprocess.run(
            ["qmd", "collection", "add", str(self.vault_path / "wiki"), "--name", self.collection_name],
            capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["qmd", "update", "--collection", self.collection_name],
            capture_output=True, text=True, timeout=30,
        )
        return self

    def __exit__(self, *exc):
        # Remove the temp collection from qmd
        subprocess.run(
            ["qmd", "collection", "remove", self.collection_name],
            capture_output=True, text=True, timeout=15,
        )
        # Clean up temp dir
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

    def qmd_update_and_embed(self):
        """Re-index the sandbox collection."""
        subprocess.run(
            ["qmd", "update", "--collection", self.collection_name],
            capture_output=True, text=True, timeout=60,
        )
        subprocess.run(
            ["qmd", "embed", "-f"],
            capture_output=True, text=True, timeout=120,
        )

    def qmd_query(self, query: str, n: int = 10) -> list[dict]:
        """Query the sandbox's qmd collection."""
        import json
        result = subprocess.run(
            ["qmd", "query", query, "-c", self.collection_name, "-n", str(n), "--json", "--no-rerank"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
