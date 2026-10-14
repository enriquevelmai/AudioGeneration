"""Tests de la app de escritorio (sin abrir ventanas) y de los añadidos de la UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from podcast_tts import __version__, cli, desktop


@pytest.fixture(autouse=True)
def _state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "state"
    monkeypatch.setenv("PODCAST_TTS_STATE_DIR", str(d))
    return d


def test_version_is_1_0_0() -> None:
    assert __version__ == "1.0.0"


def test_window_state_roundtrip_and_sanitize(_state_dir: Path) -> None:
    assert desktop.load_window_state() == {"width": desktop.DEFAULT_SIZE[0],
                                           "height": desktop.DEFAULT_SIZE[1], "x": None,
                                           "y": None, "maximized": False}
    desktop.save_window_state({"width": 1000, "height": 700, "x": 10, "y": 20, "maximized": True})
    assert desktop.load_window_state() == {"width": 1000, "height": 700, "x": 10, "y": 20,
                                           "maximized": True}
    # valores absurdos (ventana minimizada, tamaños diminutos, basura) -> por defecto
    (_state_dir / "window.json").write_text(json.dumps(
        {"width": 50, "height": "x", "x": -32000, "y": -32000}), encoding="utf-8")
    st = desktop.load_window_state()
    assert (st["width"], st["height"]) == desktop.DEFAULT_SIZE and st["x"] is None
    (_state_dir / "window.json").write_text("{no es json", encoding="utf-8")
    assert desktop.load_window_state()["width"] == desktop.DEFAULT_SIZE[0]


def test_pages_and_port() -> None:
    html = desktop.loading_html()
    assert "AudioGeneration" in html and __version__ in html
    assert "<pre>" in desktop.error_html(RuntimeError("boom <x>")) and "&lt;x&gt;" in \
        desktop.error_html(RuntimeError("boom <x>"))
    port = desktop.free_port()
    assert 0 < port < 65536


def test_falls_back_to_browser_without_pywebview(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setitem(sys.modules, "webview", None)  # import webview -> ImportError
    monkeypatch.setattr(desktop, "run_browser",
                        lambda port, voices_dir, reason=None: calls.append(reason) or 0)
    monkeypatch.setattr(desktop, "SingleInstance", _FakeInstance)
    assert desktop.run_desktop() == 0
    assert calls and "pywebview" in calls[0] and "--extra desktop" in calls[0]


def test_second_instance_does_not_start_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop, "SingleInstance", _BusyInstance)
    monkeypatch.setattr(desktop, "focus_window", lambda title=desktop.WINDOW_TITLE: True)
    monkeypatch.setattr(desktop, "Server", None)  # si se intentara arrancar, fallaría
    assert desktop.run_desktop() == 0


@pytest.mark.skipif(sys.platform != "win32", reason="mutex con nombre de Windows")
def test_single_instance_mutex() -> None:
    name = f"Local\\podcast-tts-test-{id(object())}"
    a, b = desktop.SingleInstance(name), desktop.SingleInstance(name)
    try:
        assert a.acquire() is True
        assert b.acquire() is False
    finally:
        a.release()
    assert b.acquire() is True
    b.release()


def test_cli_desktop_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake(port=0, voices_dir=None, debug=False, force_browser=False):
        seen.update(port=port, voices_dir=voices_dir, debug=debug, force_browser=force_browser)
        return 0

    monkeypatch.setattr(desktop, "run_desktop", fake)
    assert cli.main(["desktop", "--browser", "--port", "7999", "--voices-dir", "v"]) == 0
    assert seen == {"port": 7999, "voices_dir": "v", "debug": False, "force_browser": True}


def test_ui_header_and_open_output_folder(tmp_path: Path) -> None:
    pytest.importorskip("gradio")
    from podcast_tts import ui

    html = ui.header_html()
    assert "AudioGeneration" in html and f"v{__version__}" in html
    cfg = ui.UIConfig(voices_dir=tmp_path / "v", output_dir=tmp_path / "out" / "sub",
                      cache_dir=None, scripts_dir=tmp_path / "g", script_base_dir=tmp_path)
    opened = []
    msg = ui.open_output_folder(cfg, opener=opened.append)
    assert opened == [str(cfg.output_dir)] and cfg.output_dir.is_dir() and "📂" in msg

    def boom(_: str) -> None:
        raise OSError("sin explorador")

    assert "❌" in ui.open_output_folder(cfg, opener=boom)


class _FakeInstance:
    def __init__(self, *a, **k) -> None:
        pass

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        pass


class _BusyInstance(_FakeInstance):
    def acquire(self) -> bool:
        return False
