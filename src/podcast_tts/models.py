"""Catalog, status and download of the local engines' models.

Models do NOT live in the repository: they are stored in the standard caches.

- F5-TTS, F5-Spanish, Vocos and Whisper: Hugging Face cache
  (``HF_HUB_CACHE`` / ``HF_HOME``; by default ``~/.cache/huggingface/hub``),
  exactly where ``cached_path("hf://...")`` and ``hf_hub_download`` look for them
  when the engine loads.
- XTTS v2: coqui-tts models folder
  (``<TTS_HOME or XDG_DATA_HOME or %LOCALAPPDATA%>/tts/tts_models--multilingual--multi-dataset--xtts_v2``),
  the same one ``TTS.utils.manage.ModelManager`` uses. It is downloaded from the
  ``coqui/XTTS-v2`` repo with ``huggingface_hub`` (the same files coqui would fetch).

It only depends on ``huggingface_hub`` (core): it works without torch or the engines.
``download`` skips what is already complete; ``update`` always queries the
repository and fetches only the files that have changed (latest ``main`` revision).
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
    """Error resolving or downloading a model."""


@dataclass(frozen=True)
class ModelInfo:
    name: str
    title: str
    repo_id: str
    files: tuple[str, ...]          # files that must exist for it to count as downloaded
    approx_size: str
    license: str
    commercial: bool
    used_by: str
    storage: str = "hf"             # "hf" (HF cache) or "coqui" (coqui-tts folder)
    patterns: tuple[str, ...] = ()  # allow_patterns for downloading (default: files)
    optional: bool = False          # not included in "all"
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
        license="CC-BY-NC-4.0 (weights; the code is MIT)",
        commercial=False,
        used_by="f5 (English)",
    ),
    ModelInfo(
        name="f5-spanish",
        title="F5-Spanish (jpgallegoar)",
        repo_id="jpgallegoar/F5-Spanish",
        files=("model_1250000.safetensors", "vocab.txt"),
        approx_size="1.3 GB",
        license="CC-BY-NC-4.0",
        commercial=False,
        used_by="f5 (Spanish)",
    ),
    ModelInfo(
        name="vocos",
        title="Vocos mel 24 kHz (F5 vocoder)",
        repo_id="charactr/vocos-mel-24khz",
        files=("config.yaml", "pytorch_model.bin"),
        approx_size="54 MB",
        license="MIT",
        commercial=True,
        used_by="f5 (all languages)",
    ),
    ModelInfo(
        name="xtts",
        title="XTTS v2 (Coqui)",
        repo_id="coqui/XTTS-v2",
        files=("model.pth", "config.json", "vocab.json", "hash.md5", "speakers_xtts.pth"),
        approx_size="1.9 GB",
        license="Coqui Public Model License (CPML)",
        commercial=False,
        used_by="xtts (17 languages, built-in speakers)",
        storage="coqui",
        notes="Downloading it means accepting the CPML (non-commercial use).",
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
        used_by="f5, only if a voice has no ref.txt (automatic transcription)",
        optional=True,
        notes="Optional: not included in 'all'.",
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
        raise ModelsError(f"unknown model '{name}' (valid: {', '.join(_BY_NAME)}, all)")
    return _BY_NAME[key]


def resolve_names(names: list[str] | None) -> list[ModelInfo]:
    """``None``/``[]``/``["all"]`` -> all non-optional models; otherwise the given ones."""
    if not names or any(n.strip().lower() == "all" for n in names):
        return [m for m in MODELS if not m.optional]
    out: list[ModelInfo] = []
    for n in names:
        m = get_model(n)
        if m not in out:
            out.append(m)
    return out


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def _windows_local_appdata() -> Path:
    try:  # same as coqui does (trainer.io.get_user_data_dir)
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        value, _ = winreg.QueryValueEx(key, "Local AppData")
        return Path(value)
    except OSError:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def coqui_models_dir() -> Path:
    """Root folder of the coqui-tts models (equivalent to ``get_user_data_dir("tts")``)."""
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
    """Folder where the model lives (or will live)."""
    if model.storage == "coqui":
        return coqui_models_dir() / XTTS_DIR_NAME
    return _hf_repo_dir(model.repo_id)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


def _dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    seen: set[tuple[int, int]] = set()
    for p in path.rglob("*"):
        try:
            if p.is_file():
                st = p.stat()  # follows symlinks (HF cache on Linux)
                ident = (st.st_dev, st.st_ino)
                if ident in seen:
                    continue
                seen.add(ident)
                total += st.st_size
        except OSError:
            pass
    return total


def model_status(model: ModelInfo) -> dict[str, Any]:
    """Local status of a model, without accessing the network."""
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
# Download
# --------------------------------------------------------------------------- #


def download(
    model: ModelInfo,
    *,
    force_check: bool = False,
    log: Callable[[str], None] = print,
) -> Path:
    """Download ``model`` (or check for a newer version with ``force_check``).

    Without ``force_check`` it does not touch the network if the model is already complete.
    Returns the model folder.
    """
    if not force_check and model_status(model)["downloaded"]:
        log(f"  {model.name}: already downloaded in {model_dir(model)}")
        return model_dir(model)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - it is a core dependency
        raise ModelsError(f"huggingface_hub is missing ({exc}); reinstall with bats\\install.bat") from exc

    action = "checking for updates to" if force_check else "downloading"
    log(f"  {model.name}: {action} {model.repo_id} ({model.approx_size}) ...")
    kwargs: dict[str, Any] = {"repo_id": model.repo_id, "allow_patterns": model.allow_patterns}
    if model.storage == "coqui":
        # Same folder and same files as coqui-tts's ModelManager: when loading XTTS
        # coqui sees a correct hash.md5 and does not download again.
        target = model_dir(model)
        target.mkdir(parents=True, exist_ok=True)
        kwargs["local_dir"] = str(target)
    try:
        path = Path(snapshot_download(**kwargs))
    except Exception as exc:  # network, permissions, repo...
        raise ModelsError(f"could not download {model.name} from {model.url}: {exc}") from exc
    status = model_status(model)
    if not status["downloaded"]:
        raise ModelsError(
            f"{model.name}: incomplete download, missing {', '.join(status['missing'])} in {path}"
        )
    log(f"  {model.name}: OK ({human_size(status['size_bytes'])}) in {status['path']}")
    return Path(status["path"])
