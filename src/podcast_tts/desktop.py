"""Desktop app: the Gradio UI inside a native window (pywebview + WebView2).

Launch with::

    python -m podcast_tts desktop            # or: podcast-tts desktop
    pythonw -m podcast_tts desktop           # without a console (what AudioGeneration.exe does)

How it works:

- It immediately opens a window with a loading screen and, in the background, builds the app
  from :func:`podcast_tts.ui.build_app` and starts its server on ``127.0.0.1`` on a free port
  (without opening the browser). Once it responds, the window navigates to it.
- Size, position and whether it was maximized are saved on close
  (``%LOCALAPPDATA%\\AudioGeneration\\window.json``).
- Closing the window stops the server and ends the process.
- Gradio downloads open the Windows "Save as" dialog; the UI also has an
  "Open output folder" button.
- Single instance per installation (the mutex name carries a hash of the project folder):
  if one is already open, its window is brought to the front and no second server starts.
- Without a native window and without a console (pythonw), the browser opens plus a small
  window with "Open browser" and "Close AudioGeneration"; closing it stops the server.
- If pywebview (``desktop`` extra) or the WebView2 runtime is missing, it warns and opens
  the UI in the browser.

User-facing texts follow the UI language (:mod:`podcast_tts.i18n`); the window title does not
change, because the single-instance check looks the window up by title.

Requires the ``desktop`` extra (``uv sync --extra desktop``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Sequence

from .i18n import get_language, t

APP_NAME = "AudioGeneration"
WINDOW_TITLE = "AudioGeneration — Podcast TTS Studio"
APP_USER_MODEL_ID = "enriquevelmai.AudioGeneration.Desktop"
MUTEX_PREFIX = "Local\\AudioGeneration.PodcastTTS.Desktop"
LOG_MAX_BYTES = 1_000_000  # desktop.log rotates to desktop.log.1 above ~1 MB

DEFAULT_SIZE = (1320, 900)
MIN_SIZE = (900, 620)
SERVER_TIMEOUT = 180.0  # s: the first import of gradio/pandas can be slow

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def install_id(root: str | Path | None = None) -> str:
    """Short hash of the project folder (tells installations of the same user apart).

    ``launcher.py`` computes the same to check the mutex: if you change it here, change it there.
    """
    path = os.path.normcase(os.path.realpath(str(root or _PROJECT_ROOT)))
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]


def mutex_name(root: str | Path | None = None) -> str:
    """Name of the single-instance mutex of the installation in ``root``."""
    return f"{MUTEX_PREFIX}.{install_id(root)}"


MUTEX_NAME = mutex_name()
ICON_ICO = _PROJECT_ROOT / "assets" / "icon.ico"
ICON_PNG = _PROJECT_ROOT / "assets" / "icon.png"


# --------------------------------------------------------------------------- #
# Persistent state (window size, running instance, logs)
# --------------------------------------------------------------------------- #


def state_dir() -> Path:
    """Per-user state folder (``PODCAST_TTS_STATE_DIR`` replaces it, e.g. in tests)."""
    override = os.environ.get("PODCAST_TTS_STATE_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def load_window_state(path: Path | None = None) -> dict[str, Any]:
    """Saved size/position, sanitized (absurd values -> defaults)."""
    data = _read_json(path or state_dir() / "window.json")
    state: dict[str, Any] = {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1], "x": None,
                             "y": None, "maximized": False}
    try:
        w, h = int(data.get("width", 0)), int(data.get("height", 0))
        if MIN_SIZE[0] <= w <= 10000 and MIN_SIZE[1] <= h <= 10000:
            state["width"], state["height"] = w, h
        x, y = data.get("x"), data.get("y")
        if isinstance(x, int) and isinstance(y, int) and -2000 < x < 20000 and -2000 < y < 20000:
            state["x"], state["y"] = x, y
        state["maximized"] = bool(data.get("maximized", False))
    except (TypeError, ValueError):
        pass
    return state


def save_window_state(state: dict[str, Any], path: Path | None = None) -> None:
    _write_json(path or state_dir() / "window.json", state)


def _instance_file() -> Path:
    return state_dir() / f"instance-{install_id()}.json"


def _rotate_log(path: Path, max_bytes: int | None = None) -> None:
    """Simple rotation: if the log exceeds ``max_bytes`` it is renamed to ``<log>.1``."""
    try:
        if path.stat().st_size > (LOG_MAX_BYTES if max_bytes is None else max_bytes):
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass


def _setup_stdio() -> None:
    """With pythonw.exe there is no stdout/stderr: redirect them to a log so errors are kept.

    Opened in *append* mode (with rotation) and only after taking the single-instance mutex,
    so a second instance does not wipe the first one's log.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = state_dir() / "desktop.log"
    _rotate_log(log_path)
    try:
        log = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} =====\n")
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def _log(msg: str) -> None:
    try:
        print(f"[desktop {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


def _has_console() -> bool:
    """False when running under pythonw.exe (no console to show messages)."""
    exe = Path(sys.executable).name.lower()
    return not exe.startswith("pythonw") and sys.stderr is not None and sys.stderr.isatty()


def notify(message: str, title: str = APP_NAME, error: bool = False, block: bool = False) -> None:
    """Notify the user: on the console and, if there is none, with a Windows message box."""
    _log(message)
    if _has_console() or sys.platform != "win32":
        return

    def show() -> None:
        try:
            import ctypes

            flags = 0x10 if error else 0x40  # MB_ICONERROR | MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, message, title, flags | 0x10000)  # SETFOREGROUND
        except Exception:  # noqa: BLE001
            pass

    if block:
        show()
    else:
        threading.Thread(target=show, daemon=True).start()


# --------------------------------------------------------------------------- #
# Windows: AppUserModelID, single instance and bring to front
# --------------------------------------------------------------------------- #


def set_app_user_model_id() -> None:
    """So the taskbar shows the app icon instead of Python's."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001
        pass


class SingleInstance:
    """Windows named mutex: only one desktop app per user session.

    The system releases it if the process dies, so it never leaves orphan locks.
    On other systems it does nothing (always ``acquire() == True``).
    """

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle: Any = None

    def acquire(self) -> bool:
        if sys.platform != "win32":
            return True
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, self.name)
        already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        if not handle:
            return True  # without a mutex, startup is not blocked
        if already:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None and sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


def focus_window(title: str = WINDOW_TITLE) -> bool:
    """Bring the window with that title to the front. True if it was found."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    hwnd = ctypes.c_void_p(hwnd)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    else:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
    # Windows only lets the process that received the last input steal the focus: a synthetic
    # Alt key press unlocks it (a common trick with no visible effect).
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    return True


def _url_alive(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - localhost
            return resp.status < 500
    except Exception:  # noqa: BLE001
        return False


def handle_second_instance() -> int:
    """Another instance is already running: bring it to the front (or open its URL in the browser)."""
    if focus_window():
        _log("The app was already open: bringing its window to the front.")
        return 0
    info = _read_json(_instance_file())
    url = info.get("url")
    if isinstance(url, str) and _url_alive(url):
        _log(f"The app is already running (no window): opening {url} in the browser.")
        webbrowser.open(url)
        return 0
    notify(t("desktop.already_starting", app=APP_NAME))
    return 0


# --------------------------------------------------------------------------- #
# Gradio server
# --------------------------------------------------------------------------- #


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class Server:
    """The UI's Gradio server, started without blocking (``prevent_thread_lock``)."""

    def __init__(self, port: int = 0, voices_dir: str | None = None) -> None:
        self.port = port or free_port()
        self.voices_dir = voices_dir
        self.url = f"http://127.0.0.1:{self.port}/"
        self.app: Any = None

    def start(self, timeout: float = SERVER_TIMEOUT) -> str:
        from .ui import UIConfig, build_app, launch

        cfg = UIConfig(voices_dir=Path(self.voices_dir)) if self.voices_dir else UIConfig()
        self.app = build_app(cfg)
        launch(self.app, host="127.0.0.1", port=self.port, cfg=cfg, prevent_thread_lock=True,
               quiet=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _url_alive(self.url):
                _write_json(_instance_file(), {"pid": os.getpid(), "port": self.port,
                                               "url": self.url})
                return self.url
            time.sleep(0.2)
        raise TimeoutError(f"The server did not respond within {timeout:.0f} s ({self.url}).")

    def stop(self) -> None:
        if self.app is not None:
            try:
                self.app.close()
            except Exception as exc:  # noqa: BLE001
                _log(f"Warning while stopping the server: {exc!r}")
            self.app = None
        try:
            info = _read_json(_instance_file())
            if info.get("pid") == os.getpid():
                _instance_file().unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Internal pages (loading / error)
# --------------------------------------------------------------------------- #

_PAGE_CSS = """
:root { color-scheme: light dark; }
html, body { height: 100%; margin: 0; }
body { display: flex; align-items: center; justify-content: center;
       font-family: "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
       background: radial-gradient(1200px 700px at 20% 10%, #ede9fe, transparent),
                   radial-gradient(900px 600px at 90% 90%, #ffe4e6, transparent), #faf8ff;
       color: #312e81; }
@media (prefers-color-scheme: dark) {
  body { background: radial-gradient(1200px 700px at 20% 10%, #2e1065, transparent),
                     radial-gradient(900px 600px at 90% 90%, #4c0519, transparent), #0f0d1a;
         color: #e9e5ff; }
  .sub { color: #a5a1c9 !important; }
}
.box { text-align: center; padding: 24px; max-width: 640px; }
.logo { width: 112px; height: 112px; border-radius: 28px;
        box-shadow: 0 12px 40px rgba(124, 58, 237, .35); animation: pulse 1.8s ease-in-out infinite; }
h1 { font-size: 28px; margin: 22px 0 4px; font-weight: 700; letter-spacing: -.01em; }
.sub { color: #6b6894; margin: 0 0 22px; font-size: 15px; }
.bars { display: flex; gap: 6px; justify-content: center; height: 34px; align-items: center; }
.bars span { width: 6px; border-radius: 3px; background: linear-gradient(#7c3aed, #fb7185);
             animation: eq 1s ease-in-out infinite; }
.bars span:nth-child(2) { animation-delay: .15s } .bars span:nth-child(3) { animation-delay: .3s }
.bars span:nth-child(4) { animation-delay: .45s } .bars span:nth-child(5) { animation-delay: .6s }
@keyframes eq { 0%, 100% { height: 8px } 50% { height: 34px } }
@keyframes pulse { 0%, 100% { transform: scale(1) } 50% { transform: scale(1.035) } }
pre { text-align: left; white-space: pre-wrap; font-size: 12px; max-height: 300px; overflow: auto;
      background: rgba(127, 127, 127, .12); padding: 12px; border-radius: 8px; }
"""


def _icon_uri() -> str:
    import base64

    try:
        return "data:image/png;base64," + base64.b64encode(ICON_PNG.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _page(body: str) -> str:
    return (f'<!doctype html><html lang="{get_language()}"><head><meta charset="utf-8">'
            f'<title>{WINDOW_TITLE}</title><style>{_PAGE_CSS}</style></head><body><div class="box">{body}</div>'
            f"</body></html>")


def loading_html() -> str:
    from . import __version__

    logo = f'<img class="logo" src="{_icon_uri()}" alt="">' if ICON_PNG.is_file() else ""
    return _page(f'{logo}<h1>{APP_NAME}</h1><p class="sub">Podcast TTS Studio · v{__version__}'
                 f'<br>{t("desktop.loading")}</p>'
                 f'<div class="bars"><span></span><span></span><span></span><span></span>'
                 f'<span></span></div>')


def error_html(exc: BaseException) -> str:
    import html

    detail = html.escape("".join(traceback.format_exception(exc)).strip()[-4000:])
    hint = t("desktop.error_hint",
             check="<code>.venv\\Scripts\\python.exe scripts\\check_env.py</code>",
             install="<code>bats\\install.bat</code>")
    return _page(f'<h1>{t("desktop.error_title", app=APP_NAME)}</h1><p class="sub">{hint}</p>'
                 f'<pre>{detail}</pre>')


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #


def control_window(url: str, *, open_browser: Any = None, tk_module: Any = None,
                   on_ready: Any = None) -> bool:
    """Small control window when the UI is in the browser and there is no console.

    Shows "AudioGeneration is running in the browser" with [Open browser] and
    [Close AudioGeneration]. Blocks until it is closed. Returns ``False`` if tkinter is not
    available (the caller must then block some other way).
    ``tk_module`` and ``on_ready(root)`` allow testing it without really showing it.
    """
    if tk_module is None:
        try:
            import tkinter as tk_module  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 - Python without Tcl/Tk
            return False
    tk = tk_module
    open_browser = open_browser or webbrowser.open
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - e.g. broken Tcl/Tk install
        _log(f"Could not open the control window: {exc!r}")
        return False
    root.title(APP_NAME)
    root.resizable(False, False)
    try:
        if ICON_ICO.is_file():
            root.iconbitmap(str(ICON_ICO))
    except Exception:  # noqa: BLE001
        pass
    frame = tk.Frame(root, padx=24, pady=18)
    frame.pack()
    tk.Label(frame, text=t("desktop.running_in_browser", app=APP_NAME),
             font=("Segoe UI", 11, "bold")).pack(pady=(0, 4))
    tk.Label(frame, text=url, fg="#6b6894").pack(pady=(0, 14))
    buttons = tk.Frame(frame)
    buttons.pack()
    tk.Button(buttons, text=t("desktop.open_browser"), width=18,
              command=lambda: open_browser(url)).pack(side="left", padx=6)
    tk.Button(buttons, text=t("desktop.close_app", app=APP_NAME), width=22,
              command=root.destroy).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    if on_ready is not None:
        root.after(0, lambda: on_ready(root))
    root.mainloop()
    return True


def run_browser(port: int = 0, voices_dir: str | None = None, reason: str | None = None) -> int:
    """Fallback without a native window: server + default browser.

    With a console, quit with Ctrl+C. Without one (pythonw) :func:`control_window` is shown;
    closing it stops the server (and, on return, the single-instance mutex is released).
    """
    if reason:
        notify(t("desktop.opening_in_browser", reason=reason, app=APP_NAME), error=False)
    server = Server(port=port, voices_dir=voices_dir)
    try:
        url = server.start()
        webbrowser.open(url)
        if not _has_console() and control_window(url):
            _log("Control window closed: stopping the server.")
        else:
            _log(f"UI at {url} (Ctrl+C to quit)")
            server.app.block_thread()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def run_desktop(port: int = 0, voices_dir: str | None = None, debug: bool = False,
                force_browser: bool = False) -> int:
    """Open the desktop app. Returns the exit code."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    set_app_user_model_id()

    instance = SingleInstance()
    if not instance.acquire():
        return handle_second_instance()
    _setup_stdio()  # after the mutex: a second instance does not touch the first one's log
    try:
        if force_browser:
            return run_browser(port, voices_dir)
        try:
            import webview  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001 - ImportError or pythonnet/.NET failure
            return run_browser(port, voices_dir, reason=t(
                "desktop.no_pywebview", exc=f"{exc.__class__.__name__}: {exc}"))
        return _run_webview(webview, port, voices_dir, debug)
    finally:
        instance.release()


def _run_webview(webview: Any, port: int, voices_dir: str | None, debug: bool) -> int:
    server = Server(port=port, voices_dir=voices_dir)
    win_state = load_window_state()
    flags = {"renderer": None, "closed": False, "maximized": win_state["maximized"],
             "minimized": False, "error": None}

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # "Save as" for the audio files
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    except Exception:  # noqa: BLE001 - old pywebview versions
        pass

    window = webview.create_window(
        WINDOW_TITLE, html=loading_html(), width=win_state["width"], height=win_state["height"],
        x=win_state["x"], y=win_state["y"], min_size=MIN_SIZE, maximized=win_state["maximized"],
        background_color="#faf8ff", text_select=True,
    )

    def on_initialized(renderer: str) -> bool:
        flags["renderer"] = renderer
        if renderer != "edgechromium":
            return False  # MSHTML (Internet Explorer) cannot run Gradio: better use the browser
        return True

    def on_maximized() -> None:
        flags["maximized"], flags["minimized"] = True, False

    def on_minimized() -> None:
        flags["minimized"] = True

    def on_restored() -> None:
        if flags["minimized"]:
            flags["minimized"] = False
        else:
            flags["maximized"] = False

    def on_closing() -> None:
        state = dict(win_state)
        state["maximized"] = bool(flags["maximized"])
        if not flags["maximized"] and not flags["minimized"]:
            try:
                state.update(width=int(window.width), height=int(window.height),
                             x=int(window.x), y=int(window.y))
            except Exception:  # noqa: BLE001
                pass
        save_window_state(state)

    window.events.initialized += on_initialized
    window.events.maximized += on_maximized
    window.events.minimized += on_minimized
    window.events.restored += on_restored
    window.events.closing += on_closing

    def boot() -> None:
        try:
            url = server.start()
        except Exception as exc:  # noqa: BLE001
            flags["error"] = exc
            _log("Error starting the server:\n" + "".join(traceback.format_exception(exc)))
            if not flags["closed"]:
                window.load_html(error_html(exc))
            return
        if flags["closed"]:
            server.stop()
            return
        _log(f"Server ready at {url}")
        window.load_url(url)

    storage = state_dir() / "webview"
    try:
        webview.start(boot, gui="edgechromium", debug=debug, private_mode=False,
                      storage_path=str(storage),
                      icon=str(ICON_ICO) if ICON_ICO.is_file() else None)
    except Exception as exc:  # noqa: BLE001 - e.g. broken WebView2 or missing .NET
        flags["closed"] = True
        _log("Native window failure:\n" + "".join(traceback.format_exception(exc)))
        server.stop()
        return run_browser(port, voices_dir, reason=t("desktop.webview_failed", exc=exc))
    flags["closed"] = True

    if flags["renderer"] not in (None, "edgechromium"):
        server.stop()
        return run_browser(port, voices_dir, reason=t("desktop.no_webview2"))

    _log("Window closed: stopping the server.")
    server.stop()
    _log("Server stopped.")
    # The server is closed and the files are saved; tearing down .NET/WebView2 when the
    # interpreter exits can take several seconds with the process still alive (and the
    # single-instance mutex taken), so exit right away.
    _exit_now(0)
    return 0


def _exit_now(code: int) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


def build_arg_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = parser or argparse.ArgumentParser(prog="podcast_tts desktop",
                                          description=t("desktop.h_description"))
    p.add_argument("--port", type=int, default=0,
                   help=t("desktop.h_port"))
    p.add_argument("--browser", action="store_true",
                   help=t("desktop.h_browser"))
    p.add_argument("--debug", action="store_true", help=t("desktop.h_debug"))
    if parser is None:
        p.add_argument("--voices-dir", default=None, help=t("common.voices_dir_short"))
    return p


def run_from_args(args: argparse.Namespace) -> int:
    return run_desktop(port=args.port, voices_dir=getattr(args, "voices_dir", None),
                       debug=args.debug, force_browser=args.browser)


def main(argv: Sequence[str] | None = None) -> int:
    return run_from_args(build_arg_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
