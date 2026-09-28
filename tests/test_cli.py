"""CLI commands run against a throwaway vault."""

import argparse

import pytest

from pkb import config
from pkb.__main__ import cmd_rebuild
from pkb.db import get_connection


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """A one-page vault that config points at for the duration of the test."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text(
        "---\norigin: note\ntitle: A\ncreated_at: 2026-04-12\n---\n\n# A\n\nBody.\n"
    )
    monkeypatch.setattr(config, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(config, "WIKI_DIR", wiki)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / ".raw")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "pkb.db")
    return tmp_path


def _rebuild(**flags):
    args = {"force": False, "dry_run": False, "no_embed": True, **flags}
    cmd_rebuild(argparse.Namespace(**args))


def test_force_dry_run_keeps_the_index(vault, capsys):
    _rebuild()
    db = vault / "pkb.db"
    inode = db.stat().st_ino

    _rebuild(force=True, dry_run=True)

    assert db.stat().st_ino == inode
    conn = get_connection(db)
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
    conn.close()
    assert "no changes written" in capsys.readouterr().out


@pytest.mark.parametrize("force", [False, True])
def test_dry_run_without_database_creates_nothing(vault, force, capsys):
    _rebuild(force=force, dry_run=True)

    assert not (vault / "pkb.db").exists()
    assert "a real rebuild would create it" in capsys.readouterr().out
