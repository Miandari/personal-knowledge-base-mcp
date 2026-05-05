#!/usr/bin/env python3
"""Migration script: flatten wiki vault + type→origin + created_at/updated_at.

Usage:
    python scripts/migrate_flatten.py --dry-run    # preview changes
    python scripts/migrate_flatten.py --apply       # execute migration
"""

import argparse
import re
import shutil
from datetime import date
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = VAULT_ROOT / "wiki"
BACKUP_DIR = VAULT_ROOT / ".backups"

# Subdirectories to flatten
TYPE_SUBDIRS = ["concepts", "sources", "entities", "questions"]

# Origin mapping: (old_ingested_via, old_type) → new_origin
def infer_origin(fm: dict) -> str:
    ingested_via = fm.get("ingested_via", "")
    old_type = fm.get("type", "meta")

    if ingested_via == "conversation":
        return "conversation"
    if ingested_via == "notion_briefing":
        return "webpage"
    if ingested_via == "web_fetch":
        return "webpage"
    if ingested_via == "youtube_mcp":
        return "transcript"

    # Fallback based on old type
    if old_type == "source":
        return "webpage"
    if old_type == "meta":
        return "meta"
    return "note"


def infer_ingested_via(fm: dict) -> str:
    """Normalize ingested_via: old 'conversation' → 'manual'."""
    old = fm.get("ingested_via", "")
    if old == "conversation":
        return "manual"
    return old


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and return (fm_dict, body).

    Simple regex-based parser — not a full YAML parser.
    Returns raw frontmatter as dict of strings/lists.
    """
    m = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text

    fm_text = m.group(1)
    body = m.group(2)

    fm = {}
    current_key = None
    current_list = None

    for line in fm_text.split("\n"):
        # List item
        if line.startswith("  - "):
            if current_key and current_list is not None:
                val = line.strip()[2:].strip()
                # Strip quotes
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                current_list.append(val)
            continue

        # Key: value
        kv = re.match(r"^(\w[\w_]*)\s*:\s*(.*)", line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip()
            # Strip quotes
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]

            if val == "" or val == "[]":
                # Could be a list or empty
                fm[key] = []
                current_key = key
                current_list = fm[key]
            else:
                fm[key] = val
                current_key = key
                current_list = None

    return fm, body


def rebuild_frontmatter(fm: dict, field_order: list[str]) -> str:
    """Rebuild YAML frontmatter from dict, respecting field order."""
    lines = ["---"]
    emitted = set()

    for key in field_order:
        if key not in fm:
            continue
        emitted.add(key)
        val = fm[key]
        if isinstance(val, list):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in val:
                    # Wikilinks and paths with special chars get quoted
                    if "[[" in item or "/" in item or " " in item or ":" in item:
                        lines.append(f'  - "{item}"')
                    else:
                        lines.append(f"  - {item}")
        else:
            # Quote values with special characters
            if any(c in str(val) for c in [":", "#", "'", '"', "{", "}", "[", "]"]):
                lines.append(f'{key}: "{val}"')
            else:
                lines.append(f"{key}: {val}")

    # Emit any remaining fields not in the order
    for key in sorted(fm.keys()):
        if key in emitted:
            continue
        val = fm[key]
        if isinstance(val, list):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in val:
                    if "[[" in item or "/" in item or " " in item or ":" in item:
                        lines.append(f'  - "{item}"')
                    else:
                        lines.append(f"  - {item}")
        else:
            if any(c in str(val) for c in [":", "#", "'", '"', "{", "}", "[", "]"]):
                lines.append(f'{key}: "{val}"')
            else:
                lines.append(f"{key}: {val}")

    lines.append("---")
    return "\n".join(lines)


# Preferred field order in output frontmatter
FIELD_ORDER = [
    "title", "origin", "status", "ingested_via", "briefing_date",
    "aliases", "tags", "related", "sources", "raw_sources",
    "sentiment", "confidence", "author", "date_published", "url",
    "complexity", "domain", "role", "first_mentioned", "key_claims",
    "created_at", "updated_at",
]


def migrate_page(src_path: Path, dry_run: bool) -> dict:
    """Migrate a single page. Returns a summary dict."""
    text = src_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    if not fm:
        return {"file": str(src_path), "action": "skipped", "reason": "no frontmatter"}

    slug = src_path.stem
    old_type = fm.get("type", "unknown")
    old_subdir = src_path.parent.name
    old_path = f"{old_subdir}/{slug}"

    # Determine destination
    dest_path = WIKI_DIR / f"{slug}.md"

    # Check collision
    if dest_path.exists() and dest_path != src_path:
        return {"file": str(src_path), "action": "COLLISION", "dest": str(dest_path)}

    # --- Build new frontmatter ---
    new_fm = {}

    # title
    new_fm["title"] = fm.get("title", slug)

    # origin (from type)
    new_fm["origin"] = infer_origin(fm)

    # status (keep as-is)
    if "status" in fm:
        new_fm["status"] = fm["status"]

    # ingested_via (normalized)
    iv = infer_ingested_via(fm)
    if iv:
        new_fm["ingested_via"] = iv

    # briefing_date
    if "briefing_date" in fm:
        new_fm["briefing_date"] = fm["briefing_date"]

    # aliases — merge existing + old path
    aliases = []
    if "aliases" in fm and isinstance(fm["aliases"], list):
        aliases.extend(fm["aliases"])
    if old_path not in aliases:
        aliases.append(old_path)
    new_fm["aliases"] = aliases

    # tags — merge existing + namespaced type conversions
    tags = []
    if "tags" in fm and isinstance(fm["tags"], list):
        tags.extend(fm["tags"])
    if "source_type" in fm and fm["source_type"]:
        ns_tag = f"source/{fm['source_type']}"
        if ns_tag not in tags:
            tags.append(ns_tag)
    if "entity_type" in fm and fm["entity_type"]:
        ns_tag = f"entity/{fm['entity_type']}"
        if ns_tag not in tags:
            tags.append(ns_tag)
    new_fm["tags"] = tags

    # related (keep as-is, already flat wikilinks)
    new_fm["related"] = fm.get("related", [])
    if not isinstance(new_fm["related"], list):
        new_fm["related"] = []

    # sources / raw_sources — split .raw/ references
    old_sources = fm.get("sources", [])
    if not isinstance(old_sources, list):
        old_sources = []
    wiki_sources = []
    raw_sources = []
    for s in old_sources:
        # Strip wikilink brackets
        clean = s.replace("[[", "").replace("]]", "")
        if clean.startswith(".raw/"):
            raw_sources.append(clean)
        else:
            wiki_sources.append(s)
    new_fm["sources"] = wiki_sources
    if raw_sources:
        new_fm["raw_sources"] = raw_sources

    # Carry over other fields
    for field in ["sentiment", "confidence", "author", "date_published", "url",
                   "complexity", "domain", "role", "first_mentioned", "key_claims"]:
        if field in fm and fm[field]:
            new_fm[field] = fm[field]

    # created_at / updated_at
    new_fm["created_at"] = fm.get("created_at", fm.get("created", date.today().isoformat()))
    new_fm["updated_at"] = fm.get("updated_at", fm.get("updated", date.today().isoformat()))

    # Rebuild
    new_frontmatter = rebuild_frontmatter(new_fm, FIELD_ORDER)
    new_text = new_frontmatter + "\n" + body

    summary = {
        "file": str(src_path.relative_to(VAULT_ROOT)),
        "dest": str(dest_path.relative_to(VAULT_ROOT)),
        "old_type": old_type,
        "new_origin": new_fm["origin"],
        "old_path_alias": old_path,
        "action": "move" if src_path != dest_path else "rewrite",
    }

    if not dry_run:
        dest_path.write_text(new_text, encoding="utf-8")
        if src_path != dest_path:
            src_path.unlink()

    return summary


def migrate_root_page(path: Path, dry_run: bool) -> dict:
    """Migrate root-level pages (index.md, log.md) — rewrite frontmatter in place."""
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    if not fm:
        return {"file": str(path), "action": "skipped", "reason": "no frontmatter"}

    new_fm = dict(fm)

    # type → origin
    if "type" in new_fm:
        new_fm["origin"] = "meta"
        del new_fm["type"]

    # created → created_at, updated → updated_at
    if "created" in new_fm:
        new_fm["created_at"] = new_fm.pop("created")
    if "updated" in new_fm:
        new_fm["updated_at"] = new_fm.pop("updated")

    new_frontmatter = rebuild_frontmatter(new_fm, FIELD_ORDER)
    new_text = new_frontmatter + "\n" + body

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")

    return {"file": str(path.relative_to(VAULT_ROOT)), "action": "rewrite-in-place"}


def main():
    parser = argparse.ArgumentParser(description="Flatten wiki vault + type→origin migration")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes without modifying files")
    group.add_argument("--apply", action="store_true", help="Execute the migration")
    args = parser.parse_args()

    dry_run = args.dry_run

    # Backup
    if not dry_run:
        backup_dir = BACKUP_DIR / f"pre-flatten-{date.today().isoformat()}"
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(WIKI_DIR, backup_dir)
        print(f"Backup created: {backup_dir}")

    # Migrate subdirectory pages
    results = []
    for subdir_name in TYPE_SUBDIRS:
        subdir = WIKI_DIR / subdir_name
        if not subdir.exists():
            continue
        for md_file in sorted(subdir.glob("*.md")):
            result = migrate_page(md_file, dry_run)
            results.append(result)

    # Migrate root pages (index.md, log.md — NOT hot.md which has no frontmatter)
    for root_page in sorted(WIKI_DIR.glob("*.md")):
        if root_page.stem in ("hot",):
            continue
        result = migrate_root_page(root_page, dry_run)
        results.append(result)

    # Delete empty subdirectories
    if not dry_run:
        for subdir_name in TYPE_SUBDIRS:
            subdir = WIKI_DIR / subdir_name
            if subdir.exists() and not any(subdir.iterdir()):
                subdir.rmdir()
                print(f"Deleted empty directory: {subdir_name}/")

    # Print summary
    print(f"\n{'DRY RUN' if dry_run else 'MIGRATION'} SUMMARY")
    print("=" * 60)

    collisions = [r for r in results if r.get("action") == "COLLISION"]
    moves = [r for r in results if r.get("action") == "move"]
    rewrites = [r for r in results if r.get("action") in ("rewrite", "rewrite-in-place")]
    skipped = [r for r in results if r.get("action") == "skipped"]

    if collisions:
        print(f"\n⚠ COLLISIONS ({len(collisions)}):")
        for r in collisions:
            print(f"  {r['file']} → {r['dest']} ALREADY EXISTS")

    print(f"\nMoves: {len(moves)}")
    for r in moves:
        print(f"  {r['file']} → {r['dest']}")
        print(f"    type={r['old_type']} → origin={r['new_origin']}, alias={r['old_path_alias']}")

    print(f"\nRewrites: {len(rewrites)}")
    for r in rewrites:
        print(f"  {r['file']}")

    if skipped:
        print(f"\nSkipped: {len(skipped)}")
        for r in skipped:
            print(f"  {r['file']}: {r.get('reason', '?')}")

    print(f"\nTotal: {len(results)} pages processed")

    if dry_run:
        print("\nThis was a dry run. No files were modified.")
        print("Run with --apply to execute the migration.")
    else:
        print("\nMigration complete. Run: python -m pkb rebuild --force")


if __name__ == "__main__":
    main()
