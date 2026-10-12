"""Interfaz común de los motores TTS."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["EngineError", "TTSEngine"]


class EngineError(RuntimeError):
    """Error de un motor TTS (modelo no disponible, voz incompatible...)."""


@runtime_checkable
class TTSEngine(Protocol):
    """Protocolo que implementan todos los motores (f5, xtts, dummy).

    - ``name``: identificador corto ("f5", "xtts", "dummy").
    - ``sample_rate``: frecuencia de muestreo del audio devuelto.
    - ``synthesize``: devuelve ``np.ndarray`` float32 mono en [-1, 1] a
      ``sample_rate`` Hz. ``lang`` es un código ISO corto ("es", "en"...) y
      ``speed`` un factor (1.0 = normal). La voz aporta ``ref_wav``,
      ``ref_text`` y ``xtts_speaker``.
    """

    name: str

    @property
    def sample_rate(self) -> int: ...

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray: ...
