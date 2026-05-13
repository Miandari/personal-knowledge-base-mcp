#!/usr/bin/env python3
"""Migrate a pkb vault's SQLite index to the temporal-columns schema.

Adds: published_at, published_at_start, published_at_end, published_at_precision.
Drops: briefing_date (data preserved in markdown; indexer's legacy fallback
keeps existing briefing pages date-filterable via published_at).

Re-reads frontmatter to populate the new columns. Embeddings are NOT
regenerated — this is the cheap path. Use `pkb rebuild --force` instead
only if you also need to regenerate embeddings (Voyage credits).

Uses the pkb Connection helper so sqlite-vec is loaded. SQLite's
`ALTER TABLE DROP COLUMN` revalidates triggers, and the `chunks_ad`
trigger references the `chunks_vec` vec0 virtual table — without
the vec module loaded, DROP COLUMN fails.

Idempotent: safe to run multiple times.

Usage:
    python scripts/migrate_temporal_columns.py --vault ~/my-vault
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Make the pkb package importable when running this script directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pkb.dates import parse_date
from pkb.db import get_connection
from pkb.indexer import parse_markdown


SCHEMA_VERSION = 2  # bump this when adding future migrations


def _table_columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _sqlite_version() -> tuple[int, int, int]:
    parts = sqlite3.sqlite_version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def migrate(vault: Path, *, dry_run: bool = False) -> int:
    """Migrate the vault's pkb.db. Returns exit code."""
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
    to_add = []
    for col in ("published_at", "published_at_start",
                "published_at_end", "published_at_precision"):
        if col not in cols:
            to_add.append(col)

    drop_briefing_date = "briefing_date" in cols

    print(f"Migration plan for {db_path}:")
    if to_add:
        print(f"  ADD columns: {', '.join(to_add)}")
    else:
        print(f"  (new columns already present)")
    if drop_briefing_date:
        ver = _sqlite_version()
        if ver < (3, 35, 0):
            print(
                f"  ! SQLite version {sqlite3.sqlite_version} does not support "
                f"DROP COLUMN. Need ≥3.35.0. Aborting.",
                file=sys.stderr,
            )
            conn.close()
            return 2
        print(f"  DROP column: briefing_date")
    print(f"  CREATE indexes: idx_nodes_created, idx_nodes_published_start, idx_nodes_published_end")
    print(f"  RE-READ frontmatter for all pages → populate new columns (no embedding regen)")
    print(f"  SET PRAGMA user_version = {SCHEMA_VERSION}")
    if dry_run:
        print("\n(dry-run — no changes made)")
        conn.close()
        return 0

    # apsw is autocommit by default. Each statement commits independently;
    # idempotent guards above mean partial-failure rerun is safe.
    for col in to_add:
        conn.execute(f"ALTER TABLE nodes ADD COLUMN {col} TEXT")
    if drop_briefing_date:
        conn.execute("ALTER TABLE nodes DROP COLUMN briefing_date")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_published_start "
        "ON nodes(published_at_start)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_published_end "
        "ON nodes(published_at_end)"
    )

    # Re-read frontmatter and populate new columns.
    wiki_dir = vault / "wiki"
    if not wiki_dir.is_dir():
        print(f"  ! No wiki directory at {wiki_dir} — skipping frontmatter pass.",
              file=sys.stderr)
    else:
        updated = 0
        skipped = 0
        for fp in sorted(wiki_dir.glob("*.md")):
            try:
                fm, _ = parse_markdown(fp)
            except Exception as exc:
                print(f"  ! skipping {fp.name}: {exc}", file=sys.stderr)
                skipped += 1
                continue

            node_id = fp.stem
            raw = fm.get("published_at")
            if raw is None:
                # Honor legacy briefing_date as published_at, since the
                # column has been dropped from the DB.
                raw = fm.get("briefing_date")

            pd = parse_date(raw)
            conn.execute(
                """
                UPDATE nodes SET
                  published_at = ?,
                  published_at_start = ?,
                  published_at_end = ?,
                  published_at_precision = ?
                WHERE id = ?
                """,
                (
                    str(raw) if raw is not None else None,
                    pd.start if pd else None,
                    pd.end if pd else None,
                    pd.precision if pd else None,
                    node_id,
                ),
            )
            updated += 1
        print(f"  Touched {updated} pages (skipped {skipped}).")

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    conn.close()
    print(f"\nMigration complete. Schema is now at version {SCHEMA_VERSION}.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", required=True, type=Path,
                    help="Path to the pkb vault containing pkb.db and wiki/")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan but don't modify the DB.")
    args = ap.parse_args()
    sys.exit(migrate(args.vault, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
