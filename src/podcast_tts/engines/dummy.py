"""Motor de pruebas: genera un tono modulado de duración proporcional al texto."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["DummyEngine"]


class DummyEngine:
    """Motor "falso" determinista, sin dependencias pesadas (para tests y previsualizar tiempos)."""

    name = "dummy"

    def __init__(self, sample_rate: int = 24000, seconds_per_char: float = 0.06) -> None:
        self._sample_rate = sample_rate
        self.seconds_per_char = seconds_per_char
        self.calls = 0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        self.calls += 1
        speed = speed if speed and speed > 0 else 1.0
        duration = max(0.3, len(text.strip()) * self.seconds_per_char / speed)
        n = int(duration * self._sample_rate)
        t = np.arange(n, dtype=np.float64) / self._sample_rate
        # Frecuencia base distinta por voz (determinista).
        seed = int(hashlib.md5(voice.name.encode("utf-8")).hexdigest()[:8], 16)
        f0 = 140.0 + (seed % 120)
        tone = 0.6 * np.sin(2 * np.pi * f0 * t) + 0.25 * np.sin(2 * np.pi * 2 * f0 * t)
        # Envolvente tipo "sílabas" (~4 Hz) y fundidos de 20 ms.
        syll = 0.55 + 0.45 * np.sin(2 * np.pi * 4.0 * t) ** 2
        env = np.ones(n)
        ramp = min(n // 2, int(0.02 * self._sample_rate))
        if ramp > 0:
            env[:ramp] = np.linspace(0.0, 1.0, ramp)
            env[-ramp:] = np.linspace(1.0, 0.0, ramp)
        return (0.5 * tone * syll * env).astype(np.float32)
