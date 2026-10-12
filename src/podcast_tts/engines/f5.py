"""Motor F5-TTS (clonación de voz a partir de ref.wav + ref.txt).

TODO: implementar siguiendo docs/ENGINES.md (lo hará otro agente).
Requisitos de la interfaz (ver ``engines/base.py``):
- ``name = "f5"``; ``sample_rate`` (24000 para F5-TTS).
- ``synthesize(text, voice, lang, speed) -> np.ndarray`` float32 mono.
- Usar ``voice.ref_wav`` y ``voice.ref_text``; cargar el modelo de forma
  perezosa (en el primer ``synthesize``) y reutilizarlo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["F5Engine"]


class F5Engine:
    """Stub del motor F5-TTS."""

    name = "f5"

    def __init__(self, **kwargs: object) -> None:
        self.options = kwargs

    @property
    def sample_rate(self) -> int:
        return 24000

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        # TODO: implementar con f5_tts (ver docs/ENGINES.md).
        raise NotImplementedError(
            "El motor F5-TTS aún no está implementado (ver docs/ENGINES.md). "
            "Usa --engine dummy para probar."
        )
