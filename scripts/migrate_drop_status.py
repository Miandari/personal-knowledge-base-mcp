#!/usr/bin/env python3
"""Drop the legacy `status` column and its index.

The status field (seed | developing | mature | evergreen) was a manual
maturity tag that didn't earn its keep — 100% of pages in real vaults
carried whatever status the LLM stamped at creation, never updated.
Maturity is better answered by objective signals (word_count, outgoing
source edges, backlinks, updated_at) which self-maintain.

Markdown is the source of truth; existing pages keep their `status:`
frontmatter line as harmless dead metadata. The indexer no longer
reads it, and it does not appear in any MCP response.

Uses pkb.db.get_connection so sqlite-vec is loaded — SQLite revalidates
the chunks_ad trigger on ALTER TABLE DROP COLUMN, which fails without
the vec0 module.

Idempotent: safe to run multiple times.

Usage:
    python scripts/migrate_drop_status.py --vault ~/my-vault
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pkb.db import get_connection


SCHEMA_VERSION = 3


def _table_columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _sqlite_version() -> tuple[int, int, int]:
    parts = sqlite3.sqlite_version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def migrate(vault: Path, *, dry_run: bool = False) -> int:
    db_path = vault / "pkb.db"
    if not db_path.exists():
        print(f"No DB found at {db_path}. Run `pkb rebuild` first.", file=sys.stderr)
        return 1

    conn = get_connection(db_path)

    current_version = conn.execute("PRAGMA user_version").fetchone()["user_version"]
    if current_version >= SCHEMA_VERSION:
        print(f"Schema already at version {current_version}; nothing to do.")
        conn.close()
        return 0

    cols = _table_columns(conn, "nodes")
    drop_status = "status" in cols
    drop_index = any(
        row["name"] == "idx_nodes_status"
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='nodes'"
        ).fetchall()
    )

    print(f"Migration plan for {db_path}:")
    if drop_status:
        ver = _sqlite_version()
        if ver < (3, 35, 0):
            print(
                f"  ! SQLite version {sqlite3.sqlite_version} does not support "
                f"DROP COLUMN. Need ≥3.35.0. Aborting.",
                file=sys.stderr,
            )
            conn.close()
            return 2
        print(f"  DROP column: status")
    else:
        print(f"  (status column already absent)")
    if drop_index:
        print(f"  DROP index:  idx_nodes_status")
    print(f"  SET PRAGMA user_version = {SCHEMA_VERSION}")
    if dry_run:
        print("\n(dry-run — no changes made)")
        conn.close()
        return 0

    if drop_index:
        conn.execute("DROP INDEX IF EXISTS idx_nodes_status")
    if drop_status:
        conn.execute("ALTER TABLE nodes DROP COLUMN status")

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.close()
    print(f"\nMigration complete. Schema is now at version {SCHEMA_VERSION}.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", required=True, type=Path,
                    help="Path to the pkb vault containing pkb.db")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan but don't modify the DB.")
    args = ap.parse_args()
    sys.exit(migrate(args.vault, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
