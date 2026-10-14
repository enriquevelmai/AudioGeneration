"""Catálogo, estado y descarga de los modelos de los motores locales.

Los modelos NO viven en el repositorio: se guardan en las cachés estándar.

- F5-TTS, F5-Spanish, Vocos y Whisper: caché de Hugging Face
  (``HF_HUB_CACHE`` / ``HF_HOME``; por defecto ``~/.cache/huggingface/hub``),
  exactamente donde los buscan ``cached_path("hf://...")`` y ``hf_hub_download``
  al cargar el motor.
- XTTS v2: carpeta de modelos de coqui-tts
  (``<TTS_HOME o XDG_DATA_HOME o %LOCALAPPDATA%>/tts/tts_models--multilingual--multi-dataset--xtts_v2``),
  la misma que usa ``TTS.utils.manage.ModelManager``. Se descarga del repo
  ``coqui/XTTS-v2`` con ``huggingface_hub`` (mismos ficheros que bajaría coqui).

Solo depende de ``huggingface_hub`` (núcleo): funciona sin torch ni los motores.
``download`` omite lo que ya está completo; ``update`` consulta siempre el
repositorio y baja solo los ficheros que hayan cambiado (última revisión de ``main``).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "MODELS",
    "ModelInfo",
    "ModelsError",
    "coqui_models_dir",
    "download",
    "get_model",
    "model_status",
    "resolve_names",
]


class ModelsError(Exception):
    """Error al resolver o descargar un modelo."""


@dataclass(frozen=True)
class ModelInfo:
    name: str
    title: str
    repo_id: str
    files: tuple[str, ...]          # ficheros que deben existir para considerarlo descargado
    approx_size: str
    license: str
    commercial: bool
    used_by: str
    storage: str = "hf"             # "hf" (caché de HF) o "coqui" (carpeta de coqui-tts)
    patterns: tuple[str, ...] = ()  # allow_patterns para descargar (por defecto: files)
    optional: bool = False          # no se incluye en "all"
    notes: str = ""

    @property
    def allow_patterns(self) -> list[str]:
        return list(self.patterns or self.files)

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo_id}"


XTTS_DIR_NAME = "tts_models--multilingual--multi-dataset--xtts_v2"

MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        name="f5-base",
        title="F5-TTS F5TTS_v1_Base",
        repo_id="SWivid/F5-TTS",
        files=("F5TTS_v1_Base/model_1250000.safetensors",),
        approx_size="1.3 GB",
        license="CC-BY-NC-4.0 (pesos; el código es MIT)",
        commercial=False,
        used_by="f5 (inglés)",
    ),
    ModelInfo(
        name="f5-spanish",
        title="F5-Spanish (jpgallegoar)",
        repo_id="jpgallegoar/F5-Spanish",
        files=("model_1250000.safetensors", "vocab.txt"),
        approx_size="1.3 GB",
        license="CC-BY-NC-4.0",
        commercial=False,
        used_by="f5 (castellano)",
    ),
    ModelInfo(
        name="vocos",
        title="Vocos mel 24 kHz (vocoder de F5)",
        repo_id="charactr/vocos-mel-24khz",
        files=("config.yaml", "pytorch_model.bin"),
        approx_size="54 MB",
        license="MIT",
        commercial=True,
        used_by="f5 (todos los idiomas)",
    ),
    ModelInfo(
        name="xtts",
        title="XTTS v2 (Coqui)",
        repo_id="coqui/XTTS-v2",
        files=("model.pth", "config.json", "vocab.json", "hash.md5", "speakers_xtts.pth"),
        approx_size="1.9 GB",
        license="Coqui Public Model License (CPML)",
        commercial=False,
        used_by="xtts (17 idiomas, speakers integrados)",
        storage="coqui",
        notes="Descargarlo implica aceptar la CPML (uso no comercial).",
    ),
    ModelInfo(
        name="whisper",
        title="Whisper large-v3-turbo (OpenAI)",
        repo_id="openai/whisper-large-v3-turbo",
        files=("config.json", "model.safetensors"),
        patterns=("*.json", "model.safetensors", "*.txt"),
        approx_size="1.6 GB",
        license="MIT",
        commercial=True,
        used_by="f5, solo si una voz no tiene ref.txt (transcripción automática)",
        optional=True,
        notes="Opcional: no se incluye en 'all'.",
    ),
)

_BY_NAME = {m.name: m for m in MODELS}
_ALIASES = {
    "f5": "f5-base", "f5tts_v1_base": "f5-base", "f5-tts": "f5-base",
    "f5_spanish": "f5-spanish", "spanish": "f5-spanish",
    "xtts_v2": "xtts", "xtts-v2": "xtts",
}


def get_model(name: str) -> ModelInfo:
    key = (name or "").strip().lower()
    key = _ALIASES.get(key, key)
    if key not in _BY_NAME:
        raise ModelsError(f"modelo desconocido '{name}' (válidos: {', '.join(_BY_NAME)}, all)")
    return _BY_NAME[key]


def resolve_names(names: list[str] | None) -> list[ModelInfo]:
    """``None``/``[]``/``["all"]`` -> todos los no opcionales; si no, los indicados."""
    if not names or any(n.strip().lower() == "all" for n in names):
        return [m for m in MODELS if not m.optional]
    out: list[ModelInfo] = []
    for n in names:
        m = get_model(n)
        if m not in out:
            out.append(m)
    return out


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #


def _windows_local_appdata() -> Path:
    try:  # lo mismo que hace coqui (trainer.io.get_user_data_dir)
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        value, _ = winreg.QueryValueEx(key, "Local AppData")
        return Path(value)
    except OSError:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def coqui_models_dir() -> Path:
    """Carpeta raíz de modelos de coqui-tts (equivale a ``get_user_data_dir("tts")``)."""
    if os.environ.get("TTS_HOME"):
        base = Path(os.environ["TTS_HOME"]).expanduser()
    elif os.environ.get("XDG_DATA_HOME"):
        base = Path(os.environ["XDG_DATA_HOME"]).expanduser()
    elif sys.platform == "win32":
        base = _windows_local_appdata()
    elif sys.platform == "darwin":
        base = Path("~/Library/Application Support/").expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return base.resolve() / "tts"


def hf_cache_dir() -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE)


def _hf_repo_dir(repo_id: str) -> Path:
    return hf_cache_dir() / ("models--" + repo_id.replace("/", "--"))


def model_dir(model: ModelInfo) -> Path:
    """Carpeta donde vive (o vivirá) el modelo."""
    if model.storage == "coqui":
        return coqui_models_dir() / XTTS_DIR_NAME
    return _hf_repo_dir(model.repo_id)


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #


def _dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    seen: set[tuple[int, int]] = set()
    for p in path.rglob("*"):
        try:
            if p.is_file():
                st = p.stat()  # sigue symlinks (caché de HF en Linux)
                ident = (st.st_dev, st.st_ino)
                if ident in seen:
                    continue
                seen.add(ident)
                total += st.st_size
        except OSError:
            pass
    return total


def model_status(model: ModelInfo) -> dict[str, Any]:
    """Estado local de un modelo, sin acceder a la red."""
    missing: list[str] = []
    if model.storage == "coqui":
        base = model_dir(model)
        for f in model.files:
            if not (base / f).is_file():
                missing.append(f)
    else:
        from huggingface_hub import try_to_load_from_cache

        for f in model.files:
            hit = try_to_load_from_cache(model.repo_id, f)
            if not isinstance(hit, str) or not Path(hit).is_file():
                missing.append(f)
    path = model_dir(model)
    return {
        "name": model.name,
        "downloaded": not missing,
        "partial": bool(missing) and len(missing) < len(model.files) and path.exists(),
        "missing": missing,
        "path": str(path),
        "size_bytes": _dir_size(path),
    }


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} GB"


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #


def download(
    model: ModelInfo,
    *,
    force_check: bool = False,
    log: Callable[[str], None] = print,
) -> Path:
    """Descarga ``model`` (o comprueba si hay versión nueva con ``force_check``).

    Sin ``force_check`` no toca la red si el modelo ya está completo.
    Devuelve la carpeta del modelo.
    """
    if not force_check and model_status(model)["downloaded"]:
        log(f"  {model.name}: ya descargado en {model_dir(model)}")
        return model_dir(model)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - es dependencia del núcleo
        raise ModelsError(f"falta huggingface_hub ({exc}); reinstala con bats\\install.bat") from exc

    action = "comprobando actualizaciones de" if force_check else "descargando"
    log(f"  {model.name}: {action} {model.repo_id} ({model.approx_size}) ...")
    kwargs: dict[str, Any] = {"repo_id": model.repo_id, "allow_patterns": model.allow_patterns}
    if model.storage == "coqui":
        # Misma carpeta y mismos ficheros que ModelManager de coqui-tts: al cargar XTTS
        # coqui ve hash.md5 correcto y no vuelve a descargar.
        target = model_dir(model)
        target.mkdir(parents=True, exist_ok=True)
        kwargs["local_dir"] = str(target)
    try:
        path = Path(snapshot_download(**kwargs))
    except Exception as exc:  # red, permisos, repo...
        raise ModelsError(f"no se pudo descargar {model.name} desde {model.url}: {exc}") from exc
    status = model_status(model)
    if not status["downloaded"]:
        raise ModelsError(
            f"{model.name}: descarga incompleta, faltan {', '.join(status['missing'])} en {path}"
        )
    log(f"  {model.name}: OK ({human_size(status['size_bytes'])}) en {status['path']}")
    return Path(status["path"])
