"""Hace que la instalación editable funcione en carpetas con acentos o ñ.

``uv sync`` instala ``podcast_tts`` en modo editable con un fichero ``.pth`` que contiene
la ruta de ``src/`` en UTF-8. Python 3.11 lee los ``.pth`` con la codificación ANSI de
Windows (cp1252), incluso con ``PYTHONUTF8=1``, así que en una ruta como
``C:\\Users\\José\\AudioGeneration`` la ruta sale corrupta y ``import podcast_tts`` falla.

Este script sustituye el contenido de ese ``.pth`` por una línea ``import`` solo con ASCII
que calcula la ruta en tiempo de arranque a partir de ``sys.prefix`` (``<proyecto>\\.venv``),
de modo que no depende de la codificación ni de dónde esté la carpeta.

Lo ejecutan bats\\install.bat, bats\\update.bat e install_gpu.bat después de ``uv sync``::

    .venv\\Scripts\\python.exe -I -S scripts\\fix_editable_pth.py

(``-S`` porque el ``.pth`` roto podría estropear el arranque normal.) Es idempotente.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"

#: Línea ASCII que añade <carpeta de .venv>/../src a sys.path si existe.
PTH_LINE = (
    "import os, sys; [sys.path.append(p) for p in "
    "[os.path.join(os.path.dirname(sys.prefix), 'src')] "
    "if os.path.isdir(p) and p not in sys.path]\n"
)


def editable_pth_files(site_packages: Path = SITE_PACKAGES) -> list[Path]:
    """Ficheros ``.pth`` de la instalación editable de podcast_tts."""
    if not site_packages.is_dir():
        return []
    return sorted(p for p in site_packages.glob("*.pth") if "podcast_tts" in p.name)


def fix(site_packages: Path = SITE_PACKAGES) -> int:
    """Reescribe los ``.pth`` editables. Devuelve cuántos ha cambiado."""
    changed = 0
    for pth in editable_pth_files(site_packages):
        current = pth.read_bytes()
        if current == PTH_LINE.encode("ascii"):
            continue
        pth.write_bytes(PTH_LINE.encode("ascii"))
        changed += 1
    return changed


def main() -> int:
    files = editable_pth_files()
    if not files:
        print("  (no hay instalacion editable de podcast_tts: nada que ajustar)")
        return 0
    n = fix()
    print(f"  Instalacion editable ajustada para rutas con acentos ({n} fichero(s) .pth).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
