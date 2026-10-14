"""
AudioGeneration Launcher.

Compiled to AudioGeneration.exe (bats\\build_launcher.bat, PyInstaller --onefile --windowed)
and lives at the repo root. It contains neither torch nor the app: it only orchestrates.

On startup:
  1. If there is no environment (.venv), it offers to install it: runs bats\\install.bat in a
     visible console and continues when it finishes.
  2. If the app is already open (single-instance mutex of this folder), it does not look for
     updates: it launches it directly, which brings its window to the front.
     Otherwise it looks for updates without blocking startup when there is no network:
       - git clone with a remote: git fetch (short timeout); if there are new commits, it
         offers to update with bats\\update.bat /y (git pull + uv sync with the saved extras);
       - zip download: checks the latest GitHub release and, if it is newer than the
         installed one, offers to open its page.
  3. Launches .venv\\Scripts\\pythonw.exe -m podcast_tts desktop, without a console window, and
     waits a few seconds: if it dies on startup, it shows the end of the log and suggests
     reinstalling with bats\\install.bat.

Everything is logged to launcher.log (next to the exe). No network failure prevents startup.
Optional variable: AUDIOGENERATION_NO_UPDATE_CHECK=1 skips step 2.

Dialog language: English by default, Spanish with PODCAST_TTS_LANG=es (environment variable or
the project's .env file). The launcher cannot import podcast_tts (it may not be installed yet),
so it carries its own small message table.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
import webbrowser

APP = "AudioGeneration"
GITHUB_REPO = "enriquevelmai/AudioGeneration"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
#: Only release URLs of this repository are opened in the browser.
TRUSTED_URL_PREFIX = f"https://github.com/{GITHUB_REPO}/"
#: Mutex of podcast_tts.desktop (single instance). Must match desktop.mutex_name().
MUTEX_PREFIX = "Local\\AudioGeneration.PodcastTTS.Desktop"
STARTUP_CHECK = 8      # s the freshly launched app is watched
UPDATE_PULL_FAILED = 3  # exit code of bats\update.bat when git pull fails
FETCH_TIMEOUT = 8      # s
API_TIMEOUT = 4        # s
LANG_ENV = "PODCAST_TTS_LANG"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0


def repo_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


ROOT = repo_root()
VENV_SCRIPTS = os.path.join(ROOT, ".venv", "Scripts")
PYTHON = os.path.join(VENV_SCRIPTS, "python.exe")
# pythonw.exe is the console-less variant: python.exe would leave a black window behind.
PYTHONW = os.path.join(VENV_SCRIPTS, "pythonw.exe")
LOG_PATH = os.path.join(ROOT, "launcher.log")

log = logging.getLogger("launcher")


# --------------------------------------------------------------------------- messages
#: key -> (English, Spanish). English is the default language.
MESSAGES: dict[str, tuple[str, str]] = {
    "pull_failed": (
        "The new code could not be downloaded: \"git pull\" failed. The most common cause is "
        "local changes to project files (save them elsewhere and discard them, or commit "
        "them) or a branch that has diverged.\n\n"
        "Details in the bats\\update.bat console. AudioGeneration will open with the current "
        "version.",
        "No se pudo descargar el código nuevo: «git pull» falló. Lo más habitual es que "
        "tengas cambios locales en ficheros del proyecto (guárdalos aparte y descártalos, o "
        "confírmalos) o que tu rama haya divergido.\n\n"
        "Detalles en la consola de bats\\update.bat. AudioGeneration se abrirá con la versión "
        "actual."),
    "update_failed": (
        "The update finished with errors (code {code}). Check the console or launcher.log."
        "\n\nAudioGeneration will open anyway with the current version.",
        "La actualización terminó con errores (código {code}). Revisa la consola o "
        "launcher.log.\n\nAudioGeneration se abrirá igualmente con la versión actual."),
    "closed_on_start": ("AudioGeneration closed on startup (code {code}).",
                        "AudioGeneration se cerró al arrancar (código {code})."),
    "last_lines": ("Last lines of {name}:\n{text}", "Últimas líneas de {name}:\n{text}"),
    "reinstall_hint": (
        "Try reinstalling the environment with bats\\install.bat (or check it with "
        ".venv\\Scripts\\python.exe scripts\\check_env.py).",
        "Prueba a reinstalar el entorno con bats\\install.bat (o comprueba con "
        ".venv\\Scripts\\python.exe scripts\\check_env.py)."),
    "no_env": (
        "Neither the environment (.venv) nor bats\\install.bat could be found.\n\n"
        "AudioGeneration.exe must be in the project folder.",
        "No se encuentra el entorno (.venv) ni bats\\install.bat.\n\n"
        "AudioGeneration.exe debe estar en la carpeta del proyecto."),
    "install_title": ("{app} - Installation", "{app} - Instalación"),
    "install_ask": (
        "AudioGeneration is not installed in this folder yet.\n\n"
        "Install it now? A console will open with bats\\install.bat; the first time it "
        "downloads several GB (Python, PyTorch and dependencies).",
        "AudioGeneration aún no está instalado en esta carpeta.\n\n"
        "¿Instalar ahora? Se abrirá una consola con bats\\install.bat; la primera vez "
        "descarga varios GB (Python, PyTorch y dependencias)."),
    "install_incomplete": (
        "The installation did not complete (.venv does not exist).\n\n"
        "Check the bats\\install.bat console or run it by hand.",
        "La instalación no se completó (no existe .venv).\n\n"
        "Revisa la consola de bats\\install.bat o ejecútalo a mano."),
    "update_title": ("{app} - Update available", "{app} - Actualización disponible"),
    "update_ask": (
        "There are {n} new change(s) in the repository.\n\n"
        "Update now? A console will open with bats\\update.bat (git pull and dependencies).",
        "Hay {n} cambio(s) nuevo(s) en el repositorio.\n\n"
        "¿Actualizar ahora? Se abrirá una consola con bats\\update.bat (git pull y "
        "dependencias)."),
    "update_failed_title": ("{app} - Could not update", "{app} - No se pudo actualizar"),
    "release_title": ("{app} - New version", "{app} - Nueva versión"),
    "release_ask": (
        "A new version is available: {latest} (you have {current}).\n\n"
        "Open the download page? Unzip the new zip over this folder (or into another one) "
        "and run bats\\install.bat again.",
        "Hay una versión nueva: {latest} (tienes la {current}).\n\n"
        "¿Abrir la página de descarga? Descomprime el zip nuevo sobre esta carpeta (o en "
        "otra) y vuelve a ejecutar bats\\install.bat."),
    "launch_failed": (
        "AudioGeneration could not be opened:\n\n{error}\n\n"
        "Try bats\\run.bat to see the error in a console.",
        "No se pudo abrir AudioGeneration:\n\n{error}\n\n"
        "Prueba con bats\\run.bat para ver el error en consola."),
    "startup_error_title": ("{app} - Startup error", "{app} - Error al arrancar"),
    "unexpected": ("Unexpected error in the launcher:\n\n{error}\n\nDetails in launcher.log.",
                   "Error inesperado en el lanzador:\n\n{error}\n\nDetalles en launcher.log."),
}


def _normalize_lang(value: str | None) -> str | None:
    code = (value or "").strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    return code if code in ("en", "es") else None


def _lang_from_env_file(path: str) -> str | None:
    """``PODCAST_TTS_LANG`` from a ``.env`` file (simple ``KEY=value`` parser)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*(?:export\s+)?PODCAST_TTS_LANG\s*=\s*['\"]?([A-Za-z_.\-]+)",
                             line)
                if m:
                    return _normalize_lang(m.group(1))
    except OSError:
        pass
    return None


def ui_language() -> str:
    """``PODCAST_TTS_LANG`` (environment) > ``.env`` of the project > ``"en"``."""
    env_file = os.environ.get("PODCAST_TTS_ENV_FILE") or os.path.join(ROOT, ".env")
    return (_normalize_lang(os.environ.get(LANG_ENV)) or _lang_from_env_file(env_file)
            or "en")


def tr(key: str, **kwargs: object) -> str:
    """Message ``key`` in the launcher language, formatted with ``kwargs``."""
    en, es = MESSAGES[key]
    text = es if ui_language() == "es" else en
    return text.format(**kwargs) if kwargs else text


def setup_logging() -> None:
    try:
        handler: logging.Handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# --------------------------------------------------------------------------- dialogs
_tk_root = None


def _root():
    global _tk_root
    if _tk_root is None:
        import tkinter as tk

        _tk_root = tk.Tk()
        _tk_root.withdraw()
        try:
            ico = os.path.join(ROOT, "assets", "icon.ico")
            if os.path.isfile(ico):
                _tk_root.iconbitmap(default=ico)
        except Exception:  # noqa: BLE001
            pass
    return _tk_root


def ask(title: str, message: str) -> bool:
    from tkinter import messagebox

    return bool(messagebox.askyesno(title, message, parent=_root()))


def info(title: str, message: str) -> None:
    from tkinter import messagebox

    messagebox.showinfo(title, message, parent=_root())


def warn(title: str, message: str) -> None:
    from tkinter import messagebox

    messagebox.showwarning(title, message, parent=_root())


def error(title: str, message: str) -> None:
    from tkinter import messagebox

    messagebox.showerror(title, message, parent=_root())


def close_dialogs() -> None:
    global _tk_root
    if _tk_root is not None:
        try:
            _tk_root.destroy()
        except Exception:  # noqa: BLE001
            pass
        _tk_root = None


# --------------------------------------------------------------------------- utilities
def clean_env() -> dict[str, str]:
    """Environment for child processes, without the leftovers of the PyInstaller bootloader."""
    env = os.environ.copy()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and not p.startswith(meipass)]
        env["PATH"] = os.pathsep.join(parts)
        for var in ("TCL_LIBRARY", "TK_LIBRARY", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
                    "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL"):
            env.pop(var, None)
    uv_dir = os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin")
    if os.path.isdir(uv_dir) and uv_dir not in env.get("PATH", ""):
        env["PATH"] = uv_dir + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Safety belt: if the .pth of the editable install is not read correctly (paths with
    # accents on Python 3.11), podcast_tts is still imported from src\.
    src = os.path.join(ROOT, "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("COQUI_TOS_AGREED", "1")  # same as bats\run.bat
    return env


def run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=CREATE_NO_WINDOW, env=clean_env(),
    )


def bat_command_line(path: str, *args: str) -> str:
    """Safe command line to run a .bat even if its path contains ``&``, ``(``...

    ``cmd.exe /d /s /c ""path" args"``: with /s, cmd strips only the outer quotes and runs
    ``"path" args`` as is, so special characters stay quoted. (With a list
    ``["cmd.exe", "/c", path]`` subprocess does not quote paths without spaces and ``R&D``
    split the command.) ``args`` must be simple options (``/y``).
    """
    for a in args:
        if not re.fullmatch(r"[/\-A-Za-z0-9_.=:]+", a):
            raise ValueError(f"argument not allowed for a .bat: {a!r}")
    if '"' in path or "%" in path:
        raise ValueError(f"unsupported path for a .bat: {path!r}")
    tail = (" " + " ".join(args)) if args else ""
    return f'cmd.exe /d /s /c ""{path}"{tail}"'


def run_bat_visible(bat: str, *args: str) -> int:
    """Run a .bat from bats\\ in a visible console and wait for it to finish."""
    path = os.path.join(ROOT, "bats", bat)
    log.info("Running %s %s", path, " ".join(args))
    proc = subprocess.Popen(bat_command_line(path, *args), cwd=ROOT, env=clean_env(),
                            creationflags=CREATE_NEW_CONSOLE)
    code = proc.wait()
    log.info("%s finished with code %s", bat, code)
    return code


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (text or "").split("+")[0].split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def installed_version() -> str:
    """Version of podcast_tts installed in the .venv (or the one in pyproject.toml)."""
    try:
        r = run([PYTHON, "-c", "import importlib.metadata as m;print(m.version('podcast-tts'))"],
                timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read the .venv version: %r", e)
    try:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
            if m:
                return m.group(1)
    except OSError:
        pass
    return "0"


def mutex_name(root: str | None = None) -> str:
    """Name of the desktop app mutex of the installation in ``root``.

    Same as ``podcast_tts.desktop.mutex_name``: short hash of the normalized real path.
    """
    path = os.path.normcase(os.path.realpath(root or ROOT))
    return f"{MUTEX_PREFIX}.{hashlib.sha256(path.encode('utf-8')).hexdigest()[:12]}"


def app_already_running(name: str | None = None) -> bool:
    """True if the desktop app of this folder is already open (its mutex exists)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.restype = wintypes.HANDLE
        kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.OpenMutexW(0x00100000, False, name or mutex_name())  # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except Exception as e:  # noqa: BLE001
        log.info("Could not check the mutex: %r", e)
    return False


def release_page_url(rel: dict | None) -> str:
    """Release URL to open: the API one only if it belongs to this GitHub repository."""
    url = (rel or {}).get("html_url")
    if isinstance(url, str) and url.startswith(TRUSTED_URL_PREFIX) and \
            not re.search(r"[\s\"'<>\\]", url):
        return url
    if url:
        log.warning("Unexpected html_url in the GitHub response (ignored): %r", url)
    return RELEASES_PAGE


def update_failure_message(code: int) -> str:
    """Text for the user depending on the exit code of bats\\update.bat."""
    if code == UPDATE_PULL_FAILED:
        return tr("pull_failed")
    return tr("update_failed", code=code)


def tail_file(path: str, lines: int = 15) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:]).strip()
    except OSError:
        return ""


def desktop_log_path() -> str:
    base = os.environ.get("PODCAST_TTS_STATE_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP)
    return os.path.join(base, "desktop.log")


def startup_failure(proc: subprocess.Popen, timeout: float = STARTUP_CHECK) -> int | None:
    """Wait ``timeout`` s: exit code if the app died with an error, or None if it is alive."""
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return code if code else None


def startup_failure_message(code: int) -> str:
    parts = [tr("closed_on_start", code=code)]
    for name, path in (("launcher.log", LOG_PATH), ("desktop.log", desktop_log_path())):
        text = tail_file(path)
        if text:
            parts.append(tr("last_lines", name=name, text=text[-1500:]))
    parts.append(tr("reinstall_hint"))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- steps
def ensure_installed() -> bool:
    if os.path.exists(PYTHON):
        return True
    log.info("No .venv")
    if not os.path.exists(os.path.join(ROOT, "bats", "install.bat")):
        error(APP, tr("no_env"))
        return False
    if not ask(tr("install_title", app=APP), tr("install_ask")):
        return False
    run_bat_visible("install.bat")
    if not os.path.exists(PYTHON):
        error(APP, tr("install_incomplete"))
        return False
    return True


def is_git_clone_with_remote() -> bool:
    if not os.path.isdir(os.path.join(ROOT, ".git")) and \
            not os.path.isfile(os.path.join(ROOT, ".git")):
        return False
    try:
        r = run(["git", "remote"], timeout=5)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception as e:  # noqa: BLE001 - git not installed, etc.
        log.info("git not available: %r", e)
        return False


def check_git_updates() -> int:
    """Remote commits missing locally (0 if there are none or something fails)."""
    try:
        r = run(["git", "fetch", "--quiet"], timeout=FETCH_TIMEOUT)
        if r.returncode != 0:
            log.info("git fetch failed: %s", (r.stderr or r.stdout).strip())
            return 0
        r = run(["git", "rev-list", "--count", "HEAD..@{u}"], timeout=10)
        n = int((r.stdout or "0").strip() or "0") if r.returncode == 0 else 0
        log.info("New commits on the remote: %s", n)
        return n
    except subprocess.TimeoutExpired:
        log.info("git fetch exceeded %s s: skipped", FETCH_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        log.info("git check skipped: %r", e)
    return 0


def latest_release() -> dict | None:
    """Latest GitHub release ({tag_name, html_url, ...}) or None without network/release."""
    try:
        req = urllib.request.Request(RELEASES_API, headers={
            "Accept": "application/vnd.github+json", "User-Agent": f"{APP}-launcher"})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) and data.get("tag_name") else None
    except Exception as e:  # noqa: BLE001
        log.info("Release check skipped: %r", e)
        return None


def check_updates() -> None:
    if os.environ.get("AUDIOGENERATION_NO_UPDATE_CHECK") == "1":
        log.info("Update check disabled")
        return
    if is_git_clone_with_remote():
        n = check_git_updates()
        if n > 0 and ask(tr("update_title", app=APP), tr("update_ask", n=n)):
            code = run_bat_visible("update.bat", "/y")
            if code != 0:
                warn(tr("update_failed_title", app=APP), update_failure_message(code))
        return
    rel = latest_release()
    if not rel:
        return
    current, latest = installed_version(), str(rel.get("tag_name", ""))
    log.info("Installed version %s, latest release %s", current, latest)
    if parse_version(latest) > parse_version(current):
        url = release_page_url(rel)
        if ask(tr("release_title", app=APP), tr("release_ask", latest=latest, current=current)):
            webbrowser.open(url)


def launch_app() -> bool:
    exe = PYTHONW if os.path.exists(PYTHONW) else PYTHON
    cmd = [exe, "-m", "podcast_tts", "desktop"]
    log.info("Launching: %s", " ".join(cmd))
    for h in list(log.handlers):
        h.flush()
    try:
        out = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, cwd=ROOT, env=clean_env(), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=out, creationflags=CREATE_NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        log.exception("Could not launch the app")
        error(APP, tr("launch_failed", error=e))
        return False
    code = startup_failure(proc)
    out.close()
    if code is not None:
        log.error("The app exited on startup with code %s", code)
        error(tr("startup_error_title", app=APP), startup_failure_message(code))
        return False
    return True


def main() -> int:
    setup_logging()
    log.info("AudioGeneration launcher in %s", ROOT)
    try:
        if not ensure_installed():
            return 1
        if app_already_running():
            # Already open: updating now would change files in use. Launching it again only
            # brings its window to the front.
            log.info("The app is already open: skipping the update check")
        else:
            try:
                check_updates()
            except Exception:  # noqa: BLE001 - never block startup
                log.exception("Unexpected failure while checking for updates")
        close_dialogs()
        return 0 if launch_app() else 1
    except Exception as e:  # noqa: BLE001
        log.exception("Unexpected failure")
        error(APP, tr("unexpected", error=e))
        return 1
    finally:
        close_dialogs()


if __name__ == "__main__":
    sys.exit(main())
