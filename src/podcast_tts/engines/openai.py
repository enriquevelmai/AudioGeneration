"""Motor OpenAI Text-to-Speech (API REST de pago; solo stdlib, sin el SDK ``openai``).

``POST https://api.openai.com/v1/audio/speech`` con ``Authorization: Bearer <clave>`` y
``response_format=pcm`` (PCM 16 bit little-endian mono a 24 kHz).

Voz: ``provider_voice_id`` = voz de OpenAI (``alloy``, ``ash``, ``coral``, ``echo``,
``fable``, ``nova``, ``onyx``, ``sage``, ``shimmer``...). ``provider_options`` admite
``model`` e ``instructions`` (tono/estilo; solo modelos ``gpt-4o-*-tts``).

Clave: ``OPENAI_API_KEY`` (entorno o ``.env``). La política de uso de OpenAI exige
informar a los oyentes de que la voz está generada por IA.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import LicenseInfo
from .cloud import CloudEngine

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["OpenAIEngine", "API_URL", "DEFAULT_MODEL", "VOICES"]

log = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"
SPEED_RANGE = (0.25, 4.0)
VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer",
          "verse")


class OpenAIEngine(CloudEngine):
    """Motor OpenAI TTS.

    Parámetros (además de los de :class:`CloudEngine`):
        model: modelo por defecto (``gpt-4o-mini-tts``; también ``tts-1``, ``tts-1-hd``).
        instructions: instrucciones de estilo por defecto.
        base_url: URL base de la API (p.ej. un proxy compatible).
    """

    name = "openai"
    provider = "OpenAI"
    key_env = "OPENAI_API_KEY"
    required_config = ("OPENAI_API_KEY",)
    license_info = LicenseInfo(
        name="Términos de servicio de OpenAI",
        url="https://openai.com/policies/",
        commercial_use=True,
        notes="El audio generado es tuyo y puedes usarlo comercialmente según los términos "
              "de OpenAI (API de pago). Su política de uso exige avisar de que la voz es "
              "sintética.",
    )

    def __init__(self, api_key: str | None = None, *, model: str = DEFAULT_MODEL,
                 instructions: str | None = None, base_url: str = API_URL,
                 **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self.model = model
        self.instructions = instructions
        self.base_url = base_url.rstrip("/")

    def build_request(self, text: str, voice: "Voice", lang: str, speed: float = 1.0
                      ) -> tuple[str, dict[str, Any]]:
        """URL y cuerpo JSON de la petición (sin la clave)."""
        opts = self._options(voice)
        body: dict[str, Any] = {
            "model": str(opts.get("model") or self.model),
            "input": text,
            "voice": self._voice_id(voice),
            "response_format": "pcm",
        }
        speed = float(speed) if speed and speed > 0 else 1.0
        lo, hi = SPEED_RANGE
        clamped = min(max(speed, lo), hi)
        if clamped != speed:
            log.warning("OpenAI admite speed entre %g y %g; se usa %g", lo, hi, clamped)
        if abs(clamped - 1.0) > 1e-6:
            body["speed"] = clamped
        instructions = opts.get("instructions") or self.instructions
        if instructions:
            body["instructions"] = str(instructions)
        return f"{self.base_url}/audio/speech", body

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        url, body = self.build_request(text, voice, lang, speed)
        key = self._key()
        data = self._request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            secrets=(key,),
        )
        return self._to_audio(data, text)
