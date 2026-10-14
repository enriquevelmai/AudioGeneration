#!/usr/bin/env bash
# Wrapper for the podcast_tts CLI for Git Bash (and Linux): finds the project, sets
# PYTHONUTF8, PYTHONIOENCODING and COQUI_TOS_AGREED, and forwards all arguments.
#
# Project root, in this order:
#   1. PODCAST_TTS_HOME environment variable.
#   2. Target of the ~/.claude/skills/podcast-tts junction/link (-> <repo>/skill/podcast-tts).
#   3. ../../.. from this script (when run inside the repository).
#
# Examples:
#   bash ~/.claude/skills/podcast-tts/scripts/generate.sh voices list --json
#   bash ~/.claude/skills/podcast-tts/scripts/generate.sh generate /c/path/script.md -o /c/path/episode.mp3
#   bash ~/.claude/skills/podcast-tts/scripts/generate.sh --where     # prints the project root
set -euo pipefail

is_root() { [ -n "${1:-}" ] && [ -d "$1/src/podcast_tts" ]; }

link_target() {
  # Windows junction or symlink: readlink resolves it in Git Bash; otherwise use PowerShell.
  local link="$HOME/.claude/skills/podcast-tts" t=""
  [ -e "$link" ] || return 0
  t="$(readlink -f "$link" 2>/dev/null || true)"
  if [ -z "$t" ] || [ "$t" = "$link" ]; then
    if command -v powershell.exe >/dev/null 2>&1; then
      t="$(powershell.exe -NoProfile -Command \
        "(Get-Item -LiteralPath (Join-Path \$env:USERPROFILE '.claude\skills\podcast-tts') -Force).Target" \
        2>/dev/null | tr -d '\r' | head -n1 || true)"
      if [ -n "$t" ] && command -v cygpath >/dev/null 2>&1; then t="$(cygpath -u "$t")"; fi
    fi
  fi
  [ -n "$t" ] && [ "$t" != "$link" ] && printf '%s\n' "$t"
  return 0
}

ROOT=""
if is_root "${PODCAST_TTS_HOME:-}"; then
  ROOT="$PODCAST_TTS_HOME"
fi
if [ -z "$ROOT" ]; then
  t="$(link_target)"
  if [ -n "$t" ] && is_root "$t/../.."; then ROOT="$t/../.."; fi
fi
if [ -z "$ROOT" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if is_root "$here/../../.."; then ROOT="$here/../../.."; fi
fi
if [ -z "$ROOT" ]; then
  echo "Cannot find the podcast-tts project. Set PODCAST_TTS_HOME to the repository path" >&2
  echo "or reinstall the skill (scripts/install_skill.ps1)." >&2
  exit 2
fi
ROOT="$(cd "$ROOT" && pwd)"

if [ "$#" -eq 1 ] && [ "$1" = "--where" ]; then
  printf '%s\n' "$ROOT"
  exit 0
fi

PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || [ -f "$PY" ] || PY="$ROOT/.venv/bin/python"
if [ ! -f "$PY" ]; then
  echo "The environment $ROOT/.venv does not exist. Run bats\\install.bat in $ROOT." >&2
  exit 2
fi

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 COQUI_TOS_AGREED=1
exec "$PY" -m podcast_tts "$@"
