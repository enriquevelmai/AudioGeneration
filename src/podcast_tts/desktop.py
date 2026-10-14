"""App de escritorio: la UI Gradio dentro de una ventana nativa (pywebview + WebView2).

Lanzar con::

    python -m podcast_tts desktop            # o: podcast-tts desktop
    pythonw -m podcast_tts desktop           # sin consola (lo que hace AudioGeneration.exe)

Funcionamiento:

- Abre enseguida una ventana con una pantalla de carga y, en segundo plano, construye la app
  de :func:`podcast_tts.ui.build_app` y arranca su servidor en ``127.0.0.1`` en un puerto
  libre (sin abrir el navegador). Cuando responde, la ventana navega a él.
- El tamaño, la posición y si estaba maximizada se guardan al cerrar
  (``%LOCALAPPDATA%\\AudioGeneration\\window.json``).
- Al cerrar la ventana se para el servidor y termina el proceso.
- Las descargas de Gradio abren el diálogo "Guardar como" de Windows; además la UI tiene el
  botón "Abrir carpeta de salida".
- Instancia única: si ya hay una abierta, se trae su ventana al frente y no se arranca un
  segundo servidor.
- Si falta pywebview (extra ``desktop``) o el runtime WebView2, avisa y abre la UI en el
  navegador.

Requiere el extra ``desktop`` (``uv sync --extra desktop``).
"""

from __future__ import annotations

import argparse
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

APP_NAME = "AudioGeneration"
WINDOW_TITLE = "AudioGeneration — Podcast TTS Studio"
APP_USER_MODEL_ID = "enriquevelmai.AudioGeneration.Desktop"
MUTEX_NAME = "Local\\AudioGeneration.PodcastTTS.Desktop"

DEFAULT_SIZE = (1320, 900)
MIN_SIZE = (900, 620)
SERVER_TIMEOUT = 180.0  # s: la primera vez importar gradio/pandas puede tardar

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ICON_ICO = _PROJECT_ROOT / "assets" / "icon.ico"
ICON_PNG = _PROJECT_ROOT / "assets" / "icon.png"


# --------------------------------------------------------------------------- #
# Estado persistente (tamaño de ventana, instancia en marcha, logs)
# --------------------------------------------------------------------------- #


def state_dir() -> Path:
    """Carpeta de estado por usuario (``PODCAST_TTS_STATE_DIR`` la sustituye, p.ej. en tests)."""
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
    """Tamaño/posición guardados, saneados (valores absurdos -> por defecto)."""
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
    return state_dir() / "instance.json"


def _setup_stdio() -> None:
    """Con pythonw.exe no hay stdout/stderr: se redirigen a un log para no perder errores."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log = open(state_dir() / "desktop.log", "w", encoding="utf-8", errors="replace",
                   buffering=1)
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
    """False si corre con pythonw.exe (sin consola donde ver los avisos)."""
    exe = Path(sys.executable).name.lower()
    return not exe.startswith("pythonw") and sys.stderr is not None and sys.stderr.isatty()


def notify(message: str, title: str = APP_NAME, error: bool = False, block: bool = False) -> None:
    """Aviso al usuario: por consola y, si no hay consola, con un cuadro de diálogo de Windows."""
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
# Windows: AppUserModelID, instancia única y traer al frente
# --------------------------------------------------------------------------- #


def set_app_user_model_id() -> None:
    """Para que la barra de tareas muestre el icono de la app y no el de Python."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001
        pass


class SingleInstance:
    """Mutex con nombre de Windows: solo una app de escritorio por sesión de usuario.

    El sistema lo libera solo si el proceso muere, así que no deja bloqueos huérfanos.
    En otros sistemas no hace nada (siempre ``acquire() == True``).
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
            return True  # sin mutex no se bloquea el arranque
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
    """Trae al frente la ventana con ese título. True si la encontró."""
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
    # Windows solo deja robar el foco al proceso que recibió la última entrada: una pulsación
    # sintética de Alt lo desbloquea (truco habitual y sin efectos visibles).
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
    """Otra instancia ya está en marcha: traerla al frente (o abrir su URL en el navegador)."""
    if focus_window():
        _log("La app ya estaba abierta: se trae su ventana al frente.")
        return 0
    info = _read_json(_instance_file())
    url = info.get("url")
    if isinstance(url, str) and _url_alive(url):
        _log(f"La app ya está en marcha (sin ventana): se abre {url} en el navegador.")
        webbrowser.open(url)
        return 0
    notify(f"{APP_NAME} ya se está iniciando. Espera unos segundos a que aparezca la ventana.")
    return 0


# --------------------------------------------------------------------------- #
# Servidor Gradio
# --------------------------------------------------------------------------- #


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class Server:
    """El servidor Gradio de la UI, arrancado sin bloquear (``prevent_thread_lock``)."""

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
        raise TimeoutError(f"El servidor no respondió en {timeout:.0f} s ({self.url}).")

    def stop(self) -> None:
        if self.app is not None:
            try:
                self.app.close()
            except Exception as exc:  # noqa: BLE001
                _log(f"Aviso al parar el servidor: {exc!r}")
            self.app = None
        try:
            info = _read_json(_instance_file())
            if info.get("pid") == os.getpid():
                _instance_file().unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Páginas internas (carga / error)
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
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{WINDOW_TITLE}'
            f'</title><style>{_PAGE_CSS}</style></head><body><div class="box">{body}</div>'
            f"</body></html>")


def loading_html() -> str:
    from . import __version__

    logo = f'<img class="logo" src="{_icon_uri()}" alt="">' if ICON_PNG.is_file() else ""
    return _page(f'{logo}<h1>{APP_NAME}</h1><p class="sub">Podcast TTS Studio · v{__version__}'
                 f'<br>Arrancando… la primera vez puede tardar unos segundos.</p>'
                 f'<div class="bars"><span></span><span></span><span></span><span></span>'
                 f'<span></span></div>')


def error_html(exc: BaseException) -> str:
    import html

    detail = html.escape("".join(traceback.format_exception(exc)).strip()[-4000:])
    return _page(f'<h1>No se pudo arrancar {APP_NAME}</h1><p class="sub">Revisa el entorno con '
                 f'<code>.venv\\Scripts\\python.exe scripts\\check_env.py</code> o reinstala con '
                 f'<code>bats\\install.bat</code>.</p><pre>{detail}</pre>')


# --------------------------------------------------------------------------- #
# Arranque
# --------------------------------------------------------------------------- #


def run_browser(port: int = 0, voices_dir: str | None = None, reason: str | None = None) -> int:
    """Alternativa sin ventana nativa: servidor + navegador por defecto."""
    if reason:
        notify(f"{reason}\n\nSe abrirá {APP_NAME} en el navegador.", error=False)
    server = Server(port=port, voices_dir=voices_dir)
    try:
        url = server.start()
        _log(f"UI en {url} (Ctrl+C para salir)")
        webbrowser.open(url)
        server.app.block_thread()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def run_desktop(port: int = 0, voices_dir: str | None = None, debug: bool = False,
                force_browser: bool = False) -> int:
    """Abre la app de escritorio. Devuelve el código de salida."""
    _setup_stdio()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    set_app_user_model_id()

    instance = SingleInstance()
    if not instance.acquire():
        return handle_second_instance()
    try:
        if force_browser:
            return run_browser(port, voices_dir)
        try:
            import webview  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001 - ImportError o fallo de pythonnet/.NET
            return run_browser(port, voices_dir, reason=(
                "No está disponible la ventana de escritorio (pywebview): "
                f"{exc.__class__.__name__}: {exc}.\n"
                "Instálala con: uv sync --extra desktop (o vuelve a ejecutar bats\\install.bat)."))
        return _run_webview(webview, port, voices_dir, debug)
    finally:
        instance.release()


def _run_webview(webview: Any, port: int, voices_dir: str | None, debug: bool) -> int:
    server = Server(port=port, voices_dir=voices_dir)
    win_state = load_window_state()
    flags = {"renderer": None, "closed": False, "maximized": win_state["maximized"],
             "minimized": False, "error": None}

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # "Guardar como" para los audios
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    except Exception:  # noqa: BLE001 - versiones antiguas de pywebview
        pass

    window = webview.create_window(
        WINDOW_TITLE, html=loading_html(), width=win_state["width"], height=win_state["height"],
        x=win_state["x"], y=win_state["y"], min_size=MIN_SIZE, maximized=win_state["maximized"],
        background_color="#faf8ff", text_select=True,
    )

    def on_initialized(renderer: str) -> bool:
        flags["renderer"] = renderer
        if renderer != "edgechromium":
            return False  # MSHTML (Internet Explorer) no puede con Gradio: mejor el navegador
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
            _log("Error arrancando el servidor:\n" + "".join(traceback.format_exception(exc)))
            if not flags["closed"]:
                window.load_html(error_html(exc))
            return
        if flags["closed"]:
            server.stop()
            return
        _log(f"Servidor listo en {url}")
        window.load_url(url)

    storage = state_dir() / "webview"
    try:
        webview.start(boot, gui="edgechromium", debug=debug, private_mode=False,
                      storage_path=str(storage),
                      icon=str(ICON_ICO) if ICON_ICO.is_file() else None)
    except Exception as exc:  # noqa: BLE001 - p.ej. WebView2 roto o .NET ausente
        flags["closed"] = True
        _log("Fallo de la ventana nativa:\n" + "".join(traceback.format_exception(exc)))
        server.stop()
        return run_browser(port, voices_dir, reason=(
            f"No se pudo abrir la ventana de escritorio (WebView2): {exc}"))
    flags["closed"] = True

    if flags["renderer"] not in (None, "edgechromium"):
        server.stop()
        return run_browser(port, voices_dir, reason=(
            "Falta Microsoft Edge WebView2 Runtime (viene con Windows 10/11 actualizados; "
            "se descarga en https://developer.microsoft.com/microsoft-edge/webview2/)."))

    _log("Ventana cerrada: parando el servidor.")
    server.stop()
    _log("Servidor parado.")
    # El servidor ya está cerrado y los ficheros guardados; el desmontaje de .NET/WebView2 al
    # salir del intérprete puede tardar varios segundos con el proceso aún vivo (y la mutex de
    # instancia única tomada), así que se sale ya.
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
                                          description="Abre la app de escritorio.")
    p.add_argument("--port", type=int, default=0,
                   help="puerto del servidor interno (por defecto, uno libre)")
    p.add_argument("--browser", action="store_true",
                   help="no abre ventana nativa: usa el navegador (como si faltara pywebview)")
    p.add_argument("--debug", action="store_true", help="abre las herramientas de desarrollo")
    if parser is None:
        p.add_argument("--voices-dir", default=None, help="directorio de voces")
    return p


def run_from_args(args: argparse.Namespace) -> int:
    return run_desktop(port=args.port, voices_dir=getattr(args, "voices_dir", None),
                       debug=args.debug, force_browser=args.browser)


def main(argv: Sequence[str] | None = None) -> int:
    return run_from_args(build_arg_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
