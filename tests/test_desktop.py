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


# --------------------------------------------------------------------------- #
# Regresiones de la revisión de código
# --------------------------------------------------------------------------- #


def test_mutex_name_depends_on_install_folder(tmp_path: Path) -> None:
    a, b = tmp_path / "uno", tmp_path / "dos"
    a.mkdir()
    b.mkdir()
    assert desktop.mutex_name(a) != desktop.mutex_name(b)
    assert desktop.mutex_name(a).startswith(desktop.MUTEX_PREFIX + ".")
    assert desktop.MUTEX_NAME == desktop.mutex_name()


def test_second_instance_does_not_touch_log(monkeypatch, _state_dir: Path) -> None:
    _state_dir.mkdir(parents=True, exist_ok=True)
    log = _state_dir / "desktop.log"
    log.write_text("log de la primera instancia\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(desktop, "SingleInstance", _BusyInstance)
    monkeypatch.setattr(desktop, "focus_window", lambda title=desktop.WINDOW_TITLE: True)
    assert desktop.run_desktop() == 0
    assert log.read_text(encoding="utf-8") == "log de la primera instancia\n"


def test_setup_stdio_appends_and_rotates(monkeypatch, _state_dir: Path) -> None:
    _state_dir.mkdir(parents=True, exist_ok=True)
    log = _state_dir / "desktop.log"
    log.write_text("anterior\n", encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    desktop._setup_stdio()
    print("nuevo", file=sys.stderr, flush=True)
    sys.stderr.close()
    assert log.read_text(encoding="utf-8").startswith("anterior\n")
    assert "nuevo" in log.read_text(encoding="utf-8")
    # Rotación: si pasa del tamaño máximo se renombra a desktop.log.1
    monkeypatch.setattr(desktop, "LOG_MAX_BYTES", 10)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    desktop._setup_stdio()
    sys.stderr.close()
    assert "nuevo" in (_state_dir / "desktop.log.1").read_text(encoding="utf-8")
    assert "anterior" not in log.read_text(encoding="utf-8")


class _FakeWidget:
    def __init__(self, master=None, **kw) -> None:
        self.kw = kw
        _FakeTk.widgets.append(self)

    def pack(self, **kw) -> None:
        pass


class _FakeTk(_FakeWidget):
    widgets: list = []

    def __init__(self) -> None:
        super().__init__()
        self.destroyed = False
        self._after: list = []

    def title(self, *a) -> None: ...
    def resizable(self, *a) -> None: ...
    def iconbitmap(self, *a) -> None: ...
    def protocol(self, *a) -> None: ...

    def after(self, _ms, fn) -> None:
        self._after.append(fn)

    def destroy(self) -> None:
        self.destroyed = True

    def mainloop(self) -> None:
        for fn in self._after:
            fn()


class _FakeTkModule:
    Tk = _FakeTk
    Frame = _FakeWidget
    Label = _FakeWidget
    Button = _FakeWidget


def test_control_window_buttons() -> None:
    _FakeTk.widgets = []
    opened: list[str] = []

    def on_ready(root) -> None:
        buttons = {w.kw["text"]: w.kw["command"] for w in _FakeTk.widgets if "command" in w.kw}
        buttons["Abrir navegador"]()
        assert not root.destroyed
        buttons["Cerrar AudioGeneration"]()
        assert root.destroyed

    assert desktop.control_window("http://127.0.0.1:1/", open_browser=opened.append,
                                  tk_module=_FakeTkModule, on_ready=on_ready) is True
    assert opened == ["http://127.0.0.1:1/"]
    texts = [w.kw.get("text", "") for w in _FakeTk.widgets]
    assert "AudioGeneration se está ejecutando en el navegador" in texts


def test_run_browser_without_console_stops_server_when_window_closes(monkeypatch) -> None:
    events: list[str] = []

    class FakeServer:
        def __init__(self, port=0, voices_dir=None) -> None:
            self.app = None

        def start(self) -> str:
            events.append("start")
            return "http://127.0.0.1:9/"

        def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(desktop, "Server", FakeServer)
    monkeypatch.setattr(desktop, "_has_console", lambda: False)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: events.append("browser"))
    monkeypatch.setattr(desktop, "control_window",
                        lambda url, **k: events.append("window") or True)
    assert desktop.run_browser() == 0
    assert events == ["start", "browser", "window", "stop"]


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
