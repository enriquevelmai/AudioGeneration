"""Motores TTS con carga perezosa.

``get_engine("f5")`` importa ``podcast_tts.engines.f5`` solo cuando se pide,
para no cargar torch/modelos si no hacen falta. Las instancias se cachean
(un modelo por proceso).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from typing import Any

from .base import EngineError, TTSEngine

__all__ = [
    "ENGINE_NAMES",
    "EngineError",
    "TTSEngine",
    "clear_engine_cache",
    "engine_info",
    "get_engine",
]

# nombre -> (módulo, clase)
_REGISTRY: dict[str, tuple[str, str]] = {
    "f5": ("podcast_tts.engines.f5", "F5Engine"),
    "xtts": ("podcast_tts.engines.xtts", "XTTSEngine"),
    "dummy": ("podcast_tts.engines.dummy", "DummyEngine"),
}
ENGINE_NAMES: tuple[str, ...] = tuple(_REGISTRY)

_instances: dict[str, TTSEngine] = {}


def get_engine(name: str, **kwargs: Any) -> TTSEngine:
    """Devuelve (y cachea) la instancia del motor ``name``.

    Si se pasan ``kwargs`` se crea una instancia nueva sin cachear.
    """
    key = (name or "").lower()
    if key not in _REGISTRY:
        raise EngineError(f"motor desconocido '{name}' (válidos: {', '.join(ENGINE_NAMES)})")
    if not kwargs and key in _instances:
        return _instances[key]
    module_name, class_name = _REGISTRY[key]
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise EngineError(
            f"no se pudo cargar el motor '{key}': {exc}. ¿Están instaladas sus dependencias?"
        ) from exc
    engine = getattr(module, class_name)(**kwargs)
    if not kwargs:
        _instances[key] = engine
    return engine


def clear_engine_cache() -> None:
    """Olvida las instancias cacheadas (libera modelos)."""
    _instances.clear()


# nombre -> paquete del que depende (para comprobar disponibilidad sin importarlo)
_DEPENDENCIES: dict[str, str | None] = {"f5": "f5_tts", "xtts": "TTS", "dummy": None}


def _cuda_info() -> tuple[bool, str | None]:
    try:
        import torch
    except ImportError:
        return False, None
    try:
        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception:  # driver roto, etc.
        pass
    return False, None


def engine_info() -> dict[str, dict[str, Any]]:
    """Disponibilidad de cada motor, sin cargar modelos (pensado para la UI).

    Devuelve ``{nombre: {"importable": bool, "cuda": bool, "device": str | None,
    "loaded": bool, "error": str | None}}``. Solo comprueba que el paquete del
    motor está instalado (``find_spec``), no lo importa; sí importa ``torch``
    para saber si hay GPU.
    """
    cuda, device = _cuda_info()
    info: dict[str, dict[str, Any]] = {}
    for name, package in _DEPENDENCIES.items():
        importable, error = True, None
        if package is not None:
            try:
                importable = importlib.util.find_spec(package) is not None
            except (ImportError, ValueError) as exc:
                importable, error = False, str(exc)
            if not importable and error is None:
                error = f"no está instalado el paquete '{package}'"
        loaded = False
        module = sys.modules.get(_REGISTRY[name][0])
        if name == "f5" and module is not None:
            loaded = bool(getattr(module, "loaded_models", lambda: [])())
        elif name == "xtts" and module is not None:
            loaded = bool(getattr(module, "is_loaded", lambda: False)())
        elif name == "dummy":
            loaded = True
        info[name] = {
            "importable": importable,
            "cuda": cuda if name != "dummy" else False,
            "device": device if name != "dummy" else None,
            "loaded": loaded,
            "error": error,
        }
    return info
