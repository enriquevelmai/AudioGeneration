"""
AudioGeneration Launcher.

Se compila a AudioGeneration.exe (bats\\build_launcher.bat, PyInstaller --onefile --windowed)
y vive en la raiz del repo. No lleva torch ni la app dentro: solo orquesta.

Al arrancar:
  1. Si no hay entorno (.venv), ofrece instalarlo: ejecuta bats\\install.bat en una consola
     visible y, al terminar, sigue.
  2. Si la app ya esta abierta (mutex de instancia unica de esta carpeta), no busca
     actualizaciones: la lanza directamente, lo que trae su ventana al frente.
     Si no, busca actualizaciones sin bloquear el arranque si no hay red:
       - clon de git con remoto: git fetch (timeout corto); si hay commits nuevos, ofrece
         actualizar con bats\\update.bat /y (git pull + uv sync con los extras guardados);
       - descarga en zip: consulta la ultima release en GitHub y, si es mayor que la
         instalada, ofrece abrir su pagina.
  3. Lanza .venv\\Scripts\\pythonw.exe -m podcast_tts desktop, sin ventana de consola, y
     espera unos segundos: si muere al arrancar, muestra el final del log y sugiere
     reinstalar con bats\\install.bat.

Todo queda registrado en launcher.log (junto al exe). Ningun fallo de red impide arrancar.
Variable opcional: AUDIOGENERATION_NO_UPDATE_CHECK=1 omite el paso 2.
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
#: Solo se abren en el navegador URLs de releases de este repositorio.
TRUSTED_URL_PREFIX = f"https://github.com/{GITHUB_REPO}/"
#: Mutex de podcast_tts.desktop (instancia unica). Debe coincidir con desktop.mutex_name().
MUTEX_PREFIX = "Local\\AudioGeneration.PodcastTTS.Desktop"
STARTUP_CHECK = 8      # s que se vigila la app recien lanzada
UPDATE_PULL_FAILED = 3  # codigo de salida de bats\update.bat si falla git pull
FETCH_TIMEOUT = 8      # s
API_TIMEOUT = 4        # s

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0


def repo_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


ROOT = repo_root()
VENV_SCRIPTS = os.path.join(ROOT, ".venv", "Scripts")
PYTHON = os.path.join(VENV_SCRIPTS, "python.exe")
# pythonw.exe es la variante sin consola: con python.exe quedaria una ventana negra detras.
PYTHONW = os.path.join(VENV_SCRIPTS, "pythonw.exe")
LOG_PATH = os.path.join(ROOT, "launcher.log")

log = logging.getLogger("launcher")


def setup_logging() -> None:
    try:
        handler: logging.Handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# --------------------------------------------------------------------------- dialogos
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


# --------------------------------------------------------------------------- utilidades
def clean_env() -> dict[str, str]:
    """Entorno para los procesos hijos, sin los restos del bootloader de PyInstaller."""
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
    # Cinturon de seguridad: si el .pth de la instalacion editable no se lee bien (rutas con
    # acentos en Python 3.11), podcast_tts se importa igualmente desde src\.
    src = os.path.join(ROOT, "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("COQUI_TOS_AGREED", "1")  # igual que bats\run.bat
    return env


def run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=CREATE_NO_WINDOW, env=clean_env(),
    )


def bat_command_line(path: str, *args: str) -> str:
    """Linea de comandos segura para ejecutar un .bat aunque la ruta tenga ``&``, ``(``...

    ``cmd.exe /d /s /c ""ruta" args"``: con /s, cmd quita solo las comillas exteriores y
    ejecuta ``"ruta" args`` tal cual, asi que los caracteres especiales quedan entre comillas.
    (Con una lista ``["cmd.exe", "/c", ruta]`` subprocess no entrecomilla rutas sin espacios
    y ``R&D`` partia el comando.) Los ``args`` deben ser opciones simples (``/y``).
    """
    for a in args:
        if not re.fullmatch(r"[/\-A-Za-z0-9_.=:]+", a):
            raise ValueError(f"argumento no permitido para un .bat: {a!r}")
    if '"' in path or "%" in path:
        raise ValueError(f"ruta no soportada para un .bat: {path!r}")
    tail = (" " + " ".join(args)) if args else ""
    return f'cmd.exe /d /s /c ""{path}"{tail}"'


def run_bat_visible(bat: str, *args: str) -> int:
    """Ejecuta un .bat de bats\\ en una consola visible y espera a que termine."""
    path = os.path.join(ROOT, "bats", bat)
    log.info("Ejecutando %s %s", path, " ".join(args))
    proc = subprocess.Popen(bat_command_line(path, *args), cwd=ROOT, env=clean_env(),
                            creationflags=CREATE_NEW_CONSOLE)
    code = proc.wait()
    log.info("%s termino con codigo %s", bat, code)
    return code


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (text or "").split("+")[0].split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def installed_version() -> str:
    """Version de podcast_tts instalada en el .venv (o la de pyproject.toml)."""
    try:
        r = run([PYTHON, "-c", "import importlib.metadata as m;print(m.version('podcast-tts'))"],
                timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo leer la version del .venv: %r", e)
    try:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
            if m:
                return m.group(1)
    except OSError:
        pass
    return "0"


def mutex_name(root: str | None = None) -> str:
    """Nombre del mutex de la app de escritorio de la instalacion en ``root``.

    Igual que ``podcast_tts.desktop.mutex_name``: hash corto de la ruta real normalizada.
    """
    path = os.path.normcase(os.path.realpath(root or ROOT))
    return f"{MUTEX_PREFIX}.{hashlib.sha256(path.encode('utf-8')).hexdigest()[:12]}"


def app_already_running(name: str | None = None) -> bool:
    """True si la app de escritorio de esta carpeta ya esta abierta (su mutex existe)."""
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
        log.info("No se pudo comprobar el mutex: %r", e)
    return False


def release_page_url(rel: dict | None) -> str:
    """URL de la release a abrir: la de la API solo si es de este repositorio en GitHub."""
    url = (rel or {}).get("html_url")
    if isinstance(url, str) and url.startswith(TRUSTED_URL_PREFIX) and \
            not re.search(r"[\s\"'<>\\]", url):
        return url
    if url:
        log.warning("html_url inesperada en la respuesta de GitHub (se ignora): %r", url)
    return RELEASES_PAGE


def update_failure_message(code: int) -> str:
    """Texto para el usuario segun el codigo de salida de bats\\update.bat."""
    if code == UPDATE_PULL_FAILED:
        return ("No se pudo descargar el código nuevo: «git pull» falló. Lo más habitual es "
                "que tengas cambios locales en ficheros del proyecto (guárdalos aparte y "
                "descártalos, o confírmalos) o que tu rama haya divergido.\n\n"
                "Detalles en la consola de bats\\update.bat. AudioGeneration se abrirá con la "
                "versión actual.")
    return ("La actualización terminó con errores (código {}). Revisa la consola o "
            "launcher.log.\n\nAudioGeneration se abrirá igualmente con la versión actual."
            .format(code))


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
    """Espera ``timeout`` s: codigo de salida si la app murio con error, o None si sigue viva."""
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return code if code else None


def startup_failure_message(code: int) -> str:
    parts = [f"AudioGeneration se cerró al arrancar (código {code})."]
    for name, path in (("launcher.log", LOG_PATH), ("desktop.log", desktop_log_path())):
        text = tail_file(path)
        if text:
            parts.append(f"Últimas líneas de {name}:\n{text[-1500:]}")
    parts.append("Prueba a reinstalar el entorno con bats\\install.bat (o comprueba con "
                 ".venv\\Scripts\\python.exe scripts\\check_env.py).")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- pasos
def ensure_installed() -> bool:
    if os.path.exists(PYTHON):
        return True
    log.info("No hay .venv")
    if not os.path.exists(os.path.join(ROOT, "bats", "install.bat")):
        error(APP, "No se encuentra el entorno (.venv) ni bats\\install.bat.\n\n"
                   "AudioGeneration.exe debe estar en la carpeta del proyecto.")
        return False
    if not ask(f"{APP} - Instalación",
               "AudioGeneration aún no está instalado en esta carpeta.\n\n"
               "¿Instalar ahora? Se abrirá una consola con bats\\install.bat; la primera vez "
               "descarga varios GB (Python, PyTorch y dependencias)."):
        return False
    run_bat_visible("install.bat")
    if not os.path.exists(PYTHON):
        error(APP, "La instalación no se completó (no existe .venv).\n\n"
                   "Revisa la consola de bats\\install.bat o ejecútalo a mano.")
        return False
    return True


def is_git_clone_with_remote() -> bool:
    if not os.path.isdir(os.path.join(ROOT, ".git")) and \
            not os.path.isfile(os.path.join(ROOT, ".git")):
        return False
    try:
        r = run(["git", "remote"], timeout=5)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception as e:  # noqa: BLE001 - git no instalado, etc.
        log.info("git no disponible: %r", e)
        return False


def check_git_updates() -> int:
    """Commits del remoto que faltan en local (0 si no hay o si falla algo)."""
    try:
        r = run(["git", "fetch", "--quiet"], timeout=FETCH_TIMEOUT)
        if r.returncode != 0:
            log.info("git fetch fallo: %s", (r.stderr or r.stdout).strip())
            return 0
        r = run(["git", "rev-list", "--count", "HEAD..@{u}"], timeout=10)
        n = int((r.stdout or "0").strip() or "0") if r.returncode == 0 else 0
        log.info("Commits nuevos en el remoto: %s", n)
        return n
    except subprocess.TimeoutExpired:
        log.info("git fetch supero %s s: se omite", FETCH_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        log.info("Comprobacion de git omitida: %r", e)
    return 0


def latest_release() -> dict | None:
    """Ultima release de GitHub ({tag_name, html_url, ...}) o None si no hay red/release."""
    try:
        req = urllib.request.Request(RELEASES_API, headers={
            "Accept": "application/vnd.github+json", "User-Agent": f"{APP}-launcher"})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) and data.get("tag_name") else None
    except Exception as e:  # noqa: BLE001
        log.info("Consulta de releases omitida: %r", e)
        return None


def check_updates() -> None:
    if os.environ.get("AUDIOGENERATION_NO_UPDATE_CHECK") == "1":
        log.info("Comprobacion de actualizaciones desactivada")
        return
    if is_git_clone_with_remote():
        n = check_git_updates()
        if n > 0 and ask(f"{APP} - Actualización disponible",
                         f"Hay {n} cambio(s) nuevo(s) en el repositorio.\n\n"
                         "¿Actualizar ahora? Se abrirá una consola con bats\\update.bat "
                         "(git pull y dependencias)."):
            code = run_bat_visible("update.bat", "/y")
            if code != 0:
                warn(f"{APP} - No se pudo actualizar", update_failure_message(code))
        return
    rel = latest_release()
    if not rel:
        return
    current, latest = installed_version(), str(rel.get("tag_name", ""))
    log.info("Version instalada %s, ultima release %s", current, latest)
    if parse_version(latest) > parse_version(current):
        url = release_page_url(rel)
        if ask(f"{APP} - Nueva versión",
               f"Hay una versión nueva: {latest} (tienes la {current}).\n\n"
               "¿Abrir la página de descarga? Descomprime el zip nuevo sobre esta carpeta "
               "(o en otra) y vuelve a ejecutar bats\\install.bat."):
            webbrowser.open(url)


def launch_app() -> bool:
    exe = PYTHONW if os.path.exists(PYTHONW) else PYTHON
    cmd = [exe, "-m", "podcast_tts", "desktop"]
    log.info("Lanzando: %s", " ".join(cmd))
    for h in list(log.handlers):
        h.flush()
    try:
        out = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(cmd, cwd=ROOT, env=clean_env(), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=out, creationflags=CREATE_NO_WINDOW)
    except Exception as e:  # noqa: BLE001
        log.exception("No se pudo lanzar la app")
        error(APP, f"No se pudo abrir AudioGeneration:\n\n{e}\n\n"
                   "Prueba con bats\\run.bat para ver el error en consola.")
        return False
    code = startup_failure(proc)
    out.close()
    if code is not None:
        log.error("La app termino al arrancar con codigo %s", code)
        error(f"{APP} - Error al arrancar", startup_failure_message(code))
        return False
    return True


def main() -> int:
    setup_logging()
    log.info("AudioGeneration launcher en %s", ROOT)
    try:
        if not ensure_installed():
            return 1
        if app_already_running():
            # Ya abierta: actualizar ahora cambiaria ficheros en uso. Lanzarla de nuevo solo
            # trae su ventana al frente.
            log.info("La app ya esta abierta: se omite la busqueda de actualizaciones")
        else:
            try:
                check_updates()
            except Exception:  # noqa: BLE001 - nunca impedir el arranque
                log.exception("Fallo inesperado buscando actualizaciones")
        close_dialogs()
        return 0 if launch_app() else 1
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo inesperado")
        error(APP, f"Error inesperado en el lanzador:\n\n{e}\n\nDetalles en launcher.log.")
        return 1
    finally:
        close_dialogs()


if __name__ == "__main__":
    sys.exit(main())
