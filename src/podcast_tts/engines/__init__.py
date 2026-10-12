"""Motores TTS con carga perezosa.

``get_engine("f5")`` importa ``podcast_tts.engines.f5`` solo cuando se pide,
para no cargar torch/modelos si no hacen falta. Las instancias se cachean
(un modelo por proceso).
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import EngineError, TTSEngine

__all__ = ["ENGINE_NAMES", "EngineError", "TTSEngine", "clear_engine_cache", "get_engine"]

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
