"""Tests for scripts/fix_editable_pth.py (editable install in paths with accents)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("fix_editable_pth",
                                                  ROOT / "scripts" / "fix_editable_pth.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rewrites_pth_with_ascii_line_that_finds_src(tmp_path: Path) -> None:
    fix = _load()
    project = tmp_path / "José Ñandú"
    site = project / ".venv" / "Lib" / "site-packages"
    site.mkdir(parents=True)
    (project / "src").mkdir()
    pth = site / "_editable_impl_podcast_tts.pth"
    pth.write_bytes(str(project / "src").encode("utf-8"))  # what uv writes (UTF-8)
    other = site / "_virtualenv.pth"
    other.write_text("import _virtualenv", encoding="ascii")

    assert fix.fix(site) == 1
    assert pth.read_bytes().decode("ascii") == fix.PTH_LINE
    assert other.read_text(encoding="ascii") == "import _virtualenv"  # left untouched
    assert fix.fix(site) == 0  # idempotent

    # The line is executed the way site.py would, with sys.prefix = <project>\.venv
    code = (
        "import sys; sys.prefix = sys.argv[1]; "
        "exec(open(sys.argv[2], encoding='cp1252').read()); print(sys.path[-1])"
    )
    r = subprocess.run([sys.executable, "-c", code, str(project / ".venv"), str(pth)],
                       capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(project / "src")


def test_no_editable_install_is_noop(tmp_path: Path) -> None:
    fix = _load()
    assert fix.fix(tmp_path / "no-existe") == 0
    assert fix.editable_pth_files(tmp_path) == []
