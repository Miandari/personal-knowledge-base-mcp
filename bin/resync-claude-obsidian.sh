#!/usr/bin/env bash
# Resync claude-obsidian upstream into this vault.
#
# Pulls the latest from ~/Work/claude-obsidian and copies skills, commands,
# templates, hooks, and agents into the vault, preserving our local patches
# to .claude/skills/wiki-query/SKILL.md, .claude/skills/wiki-ingest/SKILL.md,
# and .claude/skills/wiki/references/frontmatter.md (these three files get
# backed up before the copy and must be manually re-reviewed after).
#
# Usage: bash bin/resync-claude-obsidian.sh

set -euo pipefail

VAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="${UPSTREAM:-$HOME/Work/claude-obsidian}"

if [ ! -d "$UPSTREAM" ]; then
  echo "error: upstream not found at $UPSTREAM" >&2
  exit 1
fi

echo "pulling upstream at $UPSTREAM"
git -C "$UPSTREAM" pull --ff-only

BACKUP="$VAULT/.resync-backup/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"

for f in \
  ".claude/skills/wiki-query/SKILL.md" \
  ".claude/skills/wiki-ingest/SKILL.md" \
  ".claude/skills/wiki/references/frontmatter.md"
do
  if [ -f "$VAULT/$f" ]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp "$VAULT/$f" "$BACKUP/$f"
    echo "backed up $f"
  fi
done

echo "copying upstream into vault"
cp -R "$UPSTREAM/skills/"* "$VAULT/.claude/skills/"
cp -R "$UPSTREAM/commands/"* "$VAULT/.claude/commands/"
cp -R "$UPSTREAM/_templates/"* "$VAULT/_templates/"
cp -R "$UPSTREAM/hooks/"* "$VAULT/hooks/"
cp -R "$UPSTREAM/agents/"* "$VAULT/.claude/agents/"

echo ""
echo "resync done. Your patched files were backed up to:"
echo "  $BACKUP"
echo ""
echo "Review upstream changes to these three files and re-apply your patches:"
echo "  - .claude/skills/wiki-query/SKILL.md        (qmd-first step 0)"
echo "  - .claude/skills/wiki-ingest/SKILL.md       (qmd reindex + multimedia + frontmatter fields)"
echo "  - .claude/skills/wiki/references/frontmatter.md  (sentiment / briefing_date / ingested_via)"
