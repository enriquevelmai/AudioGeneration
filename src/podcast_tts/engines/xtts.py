"""Motor XTTS v2 (Coqui): clonación con ref.wav o speaker integrado.

TODO: implementar siguiendo docs/ENGINES.md (lo hará otro agente).
Requisitos de la interfaz (ver ``engines/base.py``):
- ``name = "xtts"``; ``sample_rate`` (24000 para XTTS v2).
- ``synthesize(text, voice, lang, speed) -> np.ndarray`` float32 mono.
- Si ``voice.xtts_speaker`` está definido, usar ese speaker integrado; si no,
  clonar con ``voice.ref_wav``. Cargar el modelo de forma perezosa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["XTTSEngine"]


class XTTSEngine:
    """Stub del motor XTTS v2."""

    name = "xtts"

    def __init__(self, **kwargs: object) -> None:
        self.options = kwargs

    @property
    def sample_rate(self) -> int:
        return 24000

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        # TODO: implementar con coqui-tts (ver docs/ENGINES.md).
        raise NotImplementedError(
            "El motor XTTS v2 aún no está implementado (ver docs/ENGINES.md). "
            "Usa --engine dummy para probar."
        )
