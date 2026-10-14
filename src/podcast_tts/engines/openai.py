"""OpenAI Text-to-Speech engine (paid REST API; stdlib only, without the ``openai`` SDK).

``POST https://api.openai.com/v1/audio/speech`` with ``Authorization: Bearer <key>`` and
``response_format=pcm`` (16-bit little-endian mono PCM at 24 kHz).

Voice: ``provider_voice_id`` = OpenAI voice (``alloy``, ``ash``, ``coral``, ``echo``,
``fable``, ``nova``, ``onyx``, ``sage``, ``shimmer``...). ``provider_options`` accepts
``model`` and ``instructions`` (tone/style; ``gpt-4o-*-tts`` models only).

Key: ``OPENAI_API_KEY`` (environment or ``.env``). OpenAI's usage policy requires
telling listeners that the voice is AI-generated.
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
    """OpenAI TTS engine.

    Parameters (in addition to those of :class:`CloudEngine`):
        model: default model (``gpt-4o-mini-tts``; also ``tts-1``, ``tts-1-hd``).
        instructions: default style instructions.
        base_url: base URL of the API (e.g. a compatible proxy).
    """

    name = "openai"
    provider = "OpenAI"
    key_env = "OPENAI_API_KEY"
    required_config = ("OPENAI_API_KEY",)
    license_info = LicenseInfo(
        name="OpenAI Terms of Service",
        url="https://openai.com/policies/",
        commercial_use=True,
        notes="The generated audio is yours and you may use it commercially under OpenAI's "
              "terms (paid API). Their usage policy requires disclosing that the voice is "
              "synthetic.",
    )

    def __init__(self, api_key: str | None = None, *, model: str = DEFAULT_MODEL,
                 instructions: str | None = None, base_url: str = API_URL,
                 **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self.model = model
        self.instructions = instructions
        self.base_url = base_url.rstrip("/")

    @property
    def cache_tag(self) -> str:
        return f"openai|{self.model}|{self.instructions or ''}"

    def build_request(self, text: str, voice: "Voice", lang: str, speed: float = 1.0
                      ) -> tuple[str, dict[str, Any]]:
        """URL and JSON body of the request (without the key)."""
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
            log.warning("OpenAI supports speed between %g and %g; using %g", lo, hi, clamped)
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
