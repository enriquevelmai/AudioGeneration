"""Makes the editable install work in folders with accents or other non-ASCII characters.

``uv sync`` installs ``podcast_tts`` in editable mode with a ``.pth`` file that contains
the path of ``src/`` in UTF-8. Python 3.11 reads ``.pth`` files with the Windows ANSI
code page (cp1252), even with ``PYTHONUTF8=1``, so with a path such as
``C:\\Users\\José\\AudioGeneration`` the path gets corrupted and ``import podcast_tts`` fails.

This script replaces the contents of that ``.pth`` with an ASCII-only ``import`` line
that computes the path at startup from ``sys.prefix`` (``<project>\\.venv``),
so it depends neither on the encoding nor on where the folder is.

bats\\install.bat, bats\\update.bat and install_gpu.bat run it after ``uv sync``::

    .venv\\Scripts\\python.exe -I -S scripts\\fix_editable_pth.py

(``-S`` because the broken ``.pth`` could break normal startup.) It is idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"

#: ASCII line that adds <.venv folder>/../src to sys.path if it exists.
PTH_LINE = (
    "import os, sys; [sys.path.append(p) for p in "
    "[os.path.join(os.path.dirname(sys.prefix), 'src')] "
    "if os.path.isdir(p) and p not in sys.path]\n"
)


def editable_pth_files(site_packages: Path = SITE_PACKAGES) -> list[Path]:
    """``.pth`` files of the podcast_tts editable install."""
    if not site_packages.is_dir():
        return []
    return sorted(p for p in site_packages.glob("*.pth") if "podcast_tts" in p.name)


def fix(site_packages: Path = SITE_PACKAGES) -> int:
    """Rewrites the editable ``.pth`` files. Returns how many were changed."""
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
        print("  (no editable install of podcast_tts: nothing to adjust)")
        return 0
    n = fix()
    print(f"  Editable install adjusted for paths with accents ({n} .pth file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
