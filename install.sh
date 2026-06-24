#!/bin/bash
# vivarium local installer — copies the vivarium skills into ~/.claude/skills/
# (Alternative to the plugin marketplace; see README.) Never auto-installs analysis tools.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.claude/skills"
mkdir -p "$DEST"

n=0
for s in "$DIR"/skills/*/; do
  name="$(basename "$s")"
  case "$name" in
    *-workspace) continue ;;   # skip eval workspaces
  esac
  [ -f "$s/SKILL.md" ] || continue
  rm_target="$DEST/$name"
  if [ -e "$rm_target" ]; then
    # do not delete; back up the old copy with a timestamp suffix
    mv "$rm_target" "$rm_target.bak.$(date +%Y%m%d%H%M%S)"
  fi
  cp -R "$s" "$rm_target"
  echo "installed: $name"
  n=$((n + 1))
done

echo ""
echo "Done — $n vivarium skills installed to $DEST."
echo "Restart Claude Code (or run /reload) to pick them up."
echo "Note: analyses need the bio_tools conda env (seqkit/prokka/mafft/iqtree/fastANI/EzAAI/nucmer/...);"
echo "      the skills never auto-install tools — set up that env separately."
