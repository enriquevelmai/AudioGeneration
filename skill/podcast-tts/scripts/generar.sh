#!/usr/bin/env bash
# Wrapper del CLI de podcast_tts para Git Bash (y Linux): localiza el proyecto, fija
# PYTHONUTF8, PYTHONIOENCODING y COQUI_TOS_AGREED y pasa todos los argumentos.
#
# Raíz del proyecto, por este orden:
#   1. Variable de entorno PODCAST_TTS_HOME.
#   2. Destino de la junction/enlace ~/.claude/skills/podcast-tts (-> <repo>/skill/podcast-tts).
#   3. ../../.. desde este script (si se ejecuta dentro del repositorio).
#
# Ejemplos:
#   bash ~/.claude/skills/podcast-tts/scripts/generar.sh voices list --json
#   bash ~/.claude/skills/podcast-tts/scripts/generar.sh generate /c/ruta/guion.md -o /c/ruta/episodio.mp3
#   bash ~/.claude/skills/podcast-tts/scripts/generar.sh --where     # imprime la raíz del proyecto
set -euo pipefail

is_root() { [ -n "${1:-}" ] && [ -d "$1/src/podcast_tts" ]; }

link_target() {
  # Junction de Windows o symlink: readlink la resuelve en Git Bash; si no, PowerShell.
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
  echo "No se encuentra el proyecto podcast-tts. Define PODCAST_TTS_HOME con la ruta del repositorio" >&2
  echo "o reinstala la skill (scripts/install_skill.ps1)." >&2
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
  echo "No existe el entorno $ROOT/.venv. Ejecuta bats\\install.bat en $ROOT." >&2
  exit 2
fi

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 COQUI_TOS_AGREED=1
exec "$PY" -m podcast_tts "$@"
