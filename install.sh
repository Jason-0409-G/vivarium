#!/bin/bash
# vivarium local installer for Agent Skills-compatible clients.
# Copies only skill files; it never installs analysis tools or databases.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_TARGET="claude"
CUSTOM_DEST=""

usage() {
  cat <<'EOF'
Usage: bash install.sh [--target claude|codex|opencode|openclaw|hermes|both|all] [--dest DIRECTORY]

  --target claude  Install into ~/.claude/skills (default; backward compatible)
  --target codex   Install into $CODEX_HOME/skills (default: ~/.codex/skills)
  --target opencode Install into ~/.config/opencode/skills
  --target openclaw Install into ~/.openclaw/skills
  --target hermes  Install into ~/.hermes/skills/vivarium
  --target both    Install into Claude Code and Codex (backward compatible)
  --target all     Install into all five supported client directories
  --dest DIRECTORY Override the destination for a single target (testing/custom use)
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      [ "$#" -ge 2 ] || { echo "error: --target requires a value" >&2; exit 2; }
      INSTALL_TARGET="$2"
      shift 2
      ;;
    --dest)
      [ "$#" -ge 2 ] || { echo "error: --dest requires a value" >&2; exit 2; }
      CUSTOM_DEST="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$INSTALL_TARGET" in
  claude|codex|opencode|openclaw|hermes|both|all) ;;
  *)
    echo "error: unsupported --target: $INSTALL_TARGET" >&2
    exit 2
    ;;
esac

if { [ "$INSTALL_TARGET" = "both" ] || [ "$INSTALL_TARGET" = "all" ]; } && [ -n "$CUSTOM_DEST" ]; then
  echo "error: --dest cannot be combined with --target $INSTALL_TARGET" >&2
  exit 2
fi

next_backup_path() {
  local target_path="$1"
  local timestamp backup_path suffix
  timestamp="$(date +%Y%m%d%H%M%S)"
  backup_path="$target_path.bak.$timestamp"
  suffix=1
  while [ -e "$backup_path" ] || [ -L "$backup_path" ]; do
    backup_path="$target_path.bak.$timestamp.$suffix"
    suffix=$((suffix + 1))
  done
  printf '%s\n' "$backup_path"
}

install_skills() {
  local client_name="$1"
  local destination="$2"
  local count skill_dir skill_name target_path backup_path
  mkdir -p "$destination"

  count=0
  for skill_dir in "$SCRIPT_DIR"/skills/*/; do
    skill_name="$(basename "$skill_dir")"
    case "$skill_name" in
      *-workspace) continue ;;
    esac
    [ -f "$skill_dir/SKILL.md" ] || continue

    target_path="$destination/$skill_name"
    if [ -e "$target_path" ] || [ -L "$target_path" ]; then
      backup_path="$(next_backup_path "$target_path")"
      mv "$target_path" "$backup_path"
      echo "backed up: $target_path -> $backup_path"
    fi
    cp -R "$skill_dir" "$target_path"
    echo "installed [$client_name]: $skill_name"
    count=$((count + 1))
  done

  echo "Done — $count vivarium skills installed for $client_name at $destination."
}

CLAUDE_DEST="$HOME/.claude/skills"
CODEX_BASE="${CODEX_HOME:-$HOME/.codex}"
CODEX_DEST="$CODEX_BASE/skills"
OPENCODE_DEST="$HOME/.config/opencode/skills"
OPENCLAW_DEST="$HOME/.openclaw/skills"
HERMES_DEST="$HOME/.hermes/skills/vivarium"

case "$INSTALL_TARGET" in
  claude)
    install_skills "Claude Code" "${CUSTOM_DEST:-$CLAUDE_DEST}"
    echo "Restart Claude Code if the new skills are not discovered automatically."
    ;;
  codex)
    install_skills "Codex" "${CUSTOM_DEST:-$CODEX_DEST}"
    echo "The skills are available to Codex on the next turn; restart if discovery does not refresh."
    ;;
  opencode)
    install_skills "OpenCode" "${CUSTOM_DEST:-$OPENCODE_DEST}"
    echo "Start a new OpenCode session if skill discovery does not refresh."
    ;;
  openclaw)
    install_skills "OpenClaw" "${CUSTOM_DEST:-$OPENCLAW_DEST}"
    echo "Start a new OpenClaw session if skill discovery does not refresh."
    ;;
  hermes)
    install_skills "Hermes" "${CUSTOM_DEST:-$HERMES_DEST}"
    echo "Start a new Hermes session if skill discovery does not refresh."
    ;;
  both)
    install_skills "Claude Code" "$CLAUDE_DEST"
    install_skills "Codex" "$CODEX_DEST"
    echo "Restart either client if skill discovery does not refresh."
    ;;
  all)
    install_skills "Claude Code" "$CLAUDE_DEST"
    install_skills "Codex" "$CODEX_DEST"
    install_skills "OpenCode" "$OPENCODE_DEST"
    install_skills "OpenClaw" "$OPENCLAW_DEST"
    install_skills "Hermes" "$HERMES_DEST"
    echo "Start a new client session if skill discovery does not refresh."
    ;;
esac

echo "Note: analyses require external bioinformatics tools (for example seqkit, Prokka, MAFFT, IQ-TREE, FastANI, EzAAI, and MUMmer)."
echo "      This installer never installs tools or databases; configure the analysis environment separately."
