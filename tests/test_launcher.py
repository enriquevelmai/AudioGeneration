"""Tests de launcher.py (AudioGeneration.exe) sin compilarlo ni abrir diálogos."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def launcher():
    spec = importlib.util.spec_from_file_location("ag_launcher", ROOT / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mutex_name_matches_desktop(launcher, tmp_path: Path) -> None:
    from podcast_tts import desktop

    assert launcher.mutex_name() == desktop.mutex_name() == desktop.MUTEX_NAME
    other = tmp_path / "otra instalación"
    other.mkdir()
    assert launcher.mutex_name(str(other)) == desktop.mutex_name(other)
    assert launcher.mutex_name(str(other)) != launcher.mutex_name()
    # Mayúsculas/minúsculas y barras no cambian el nombre en Windows
    if sys.platform == "win32":
        assert launcher.mutex_name(str(other).upper()) == launcher.mutex_name(str(other))


@pytest.mark.skipif(sys.platform != "win32", reason="mutex con nombre de Windows")
def test_app_already_running_detects_desktop_mutex(launcher, tmp_path: Path) -> None:
    from podcast_tts import desktop

    name = desktop.mutex_name(tmp_path)
    assert launcher.app_already_running(name) is False
    inst = desktop.SingleInstance(name)
    try:
        assert inst.acquire() is True
        assert launcher.app_already_running(name) is True
    finally:
        inst.release()
    assert launcher.app_already_running(name) is False


def test_main_skips_update_check_when_app_running(launcher, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(launcher, "setup_logging", lambda: None)
    monkeypatch.setattr(launcher, "ensure_installed", lambda: True)
    monkeypatch.setattr(launcher, "app_already_running", lambda name=None: True)
    monkeypatch.setattr(launcher, "check_updates", lambda: calls.append("updates"))
    monkeypatch.setattr(launcher, "launch_app", lambda: calls.append("launch") or True)
    assert launcher.main() == 0
    assert calls == ["launch"]
    monkeypatch.setattr(launcher, "app_already_running", lambda name=None: False)
    calls.clear()
    assert launcher.main() == 0
    assert calls == ["updates", "launch"]


@pytest.mark.parametrize("url, ok", [
    ("https://github.com/enriquevelmai/AudioGeneration/releases/tag/v1.1.0", True),
    ("https://github.com/enriquevelmai/AudioGeneration.evil.com/x", False),
    ("https://evil.example/enriquevelmai/AudioGeneration/", False),
    ("http://github.com/enriquevelmai/AudioGeneration/releases", False),
    ("file:///C:/Windows/System32/calc.exe", False),
    ("https://github.com/enriquevelmai/AudioGeneration/x\" & calc", False),
    (None, False),
    (123, False),
])
def test_release_page_url_only_trusts_this_repo(launcher, url, ok: bool) -> None:
    result = launcher.release_page_url({"html_url": url})
    assert result == (url if ok else launcher.RELEASES_PAGE)
    assert launcher.release_page_url(None) == launcher.RELEASES_PAGE


def test_bat_command_line_rejects_odd_args(launcher) -> None:
    with pytest.raises(ValueError):
        launcher.bat_command_line(r"C:\x\a.bat", "/y & calc")
    with pytest.raises(ValueError):
        launcher.bat_command_line('C:\\x"\\a.bat')


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
@pytest.mark.parametrize("dirname", ["R&D dir", "R&D", "a (b) c", "José Ñandú", "x[1]!"])
def test_bat_command_line_runs_bat_in_odd_paths(launcher, tmp_path: Path, dirname: str) -> None:
    d = tmp_path / dirname
    d.mkdir()
    bat = d / "eco.bat"
    out = tmp_path / "out.txt"
    # out está en tmp_path (ASCII): el .bat se puede escribir en ASCII puro.
    bat.write_bytes(f'@echo off\r\n> "{out}" echo ok %1\r\nexit /b 7\r\n'.encode("ascii"))
    r = subprocess.run(launcher.bat_command_line(str(bat), "/y"), cwd=str(d))
    assert r.returncode == 7
    assert out.read_text().strip() == "ok /y"


def test_update_failure_message(launcher) -> None:
    assert "cambios locales" in launcher.update_failure_message(launcher.UPDATE_PULL_FAILED)
    assert "código 1" in launcher.update_failure_message(1)


def test_startup_failure_detection(launcher, tmp_path: Path, monkeypatch) -> None:
    dead = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(1)"])
    assert launcher.startup_failure(dead, timeout=20) == 1
    ok = subprocess.Popen([sys.executable, "-c", "pass"])
    assert launcher.startup_failure(ok, timeout=20) is None  # salida limpia (2.ª instancia)
    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert launcher.startup_failure(alive, timeout=0.5) is None
    finally:
        alive.kill()
    log = tmp_path / "launcher.log"
    log.write_text("linea 1\nNo module named podcast_tts\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "LOG_PATH", str(log))
    monkeypatch.setenv("PODCAST_TTS_STATE_DIR", str(tmp_path / "state"))
    msg = launcher.startup_failure_message(1)
    assert "No module named podcast_tts" in msg and "install.bat" in msg


def test_clean_env_sets_pythonpath_to_src(launcher, monkeypatch) -> None:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = launcher.clean_env()
    assert env["PYTHONPATH"].split(";")[0] == str(Path(launcher.ROOT) / "src")
    monkeypatch.setenv("PYTHONPATH", "C:\\otra")
    assert launcher.clean_env()["PYTHONPATH"].endswith(";C:\\otra")
