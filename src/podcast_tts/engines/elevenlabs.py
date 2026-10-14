"""ElevenLabs engine (paid REST API; stdlib only).

``POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_24000``
with the ``xi-api-key`` header. Returns 16-bit mono PCM at 24 kHz.

Voice: ``provider_voice_id`` = ElevenLabs voice ID (e.g. ``21m00Tcm4TlvDq8ikWAM``).
``provider_options`` accepts ``model_id``, ``voice_settings`` (``stability``,
``similarity_boost``, ``style``, ``use_speaker_boost``, ``speed``), ``language_code``
(otherwise the language is only sent to the models that support it) and ``seed``.

Key: ``ELEVENLABS_API_KEY`` (environment or ``.env``).
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import COMMERCIAL_DEPENDS, LicenseInfo
from .cloud import CloudEngine

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["ElevenLabsEngine", "DEFAULT_MODEL", "API_URL"]

log = logging.getLogger(__name__)

API_URL = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = "pcm_24000"
SPEED_RANGE = (0.7, 1.2)
# Models that accept ``language_code`` (with others the API returns an error).
# For other models it can be forced with ``provider_options.language_code``.
LANGUAGE_CODE_MODELS = frozenset({"eleven_turbo_v2_5", "eleven_flash_v2_5"})


class ElevenLabsEngine(CloudEngine):
    """ElevenLabs engine.

    Parameters (in addition to those of :class:`CloudEngine`):
        model_id: default model (``eleven_multilingual_v2``).
        voice_settings: default settings (merged with the voice's own).
        base_url: base URL of the API.
    """

    name = "elevenlabs"
    provider = "ElevenLabs"
    key_env = "ELEVENLABS_API_KEY"
    required_config = ("ELEVENLABS_API_KEY",)
    license_info = LicenseInfo(
        name="ElevenLabs Terms of Service",
        url="https://elevenlabs.io/terms-of-use",
        commercial_use=COMMERCIAL_DEPENDS,
        notes="Commercial use allowed with a paid plan (the free plan is non-commercial and "
              "requires attribution). Subject to their terms and usage policy; cloning a voice "
              "requires the consent of its owner.",
    )

    def __init__(self, api_key: str | None = None, *, model_id: str = DEFAULT_MODEL,
                 voice_settings: dict[str, Any] | None = None, base_url: str = API_URL,
                 **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self.model_id = model_id
        self.voice_settings = dict(voice_settings or {})
        self.base_url = base_url.rstrip("/")

    @property
    def cache_tag(self) -> str:
        settings = json.dumps(self.voice_settings, sort_keys=True, default=str)
        return f"elevenlabs|{self.model_id}|{OUTPUT_FORMAT}|{settings}"

    def build_request(self, text: str, voice: "Voice", lang: str, speed: float = 1.0
                      ) -> tuple[str, dict[str, Any]]:
        """URL and JSON body of the request (without the key)."""
        opts = self._options(voice)
        voice_id = self._voice_id(voice)
        model = str(opts.get("model_id") or self.model_id)
        settings = {**self.voice_settings, **dict(opts.get("voice_settings") or {})}
        speed = float(speed) if speed and speed > 0 else 1.0
        if abs(speed - 1.0) > 1e-6:
            lo, hi = SPEED_RANGE
            clamped = min(max(speed, lo), hi)
            if clamped != speed:
                log.warning("ElevenLabs supports speed between %g and %g; using %g instead of %g",
                            lo, hi, clamped, speed)
            settings["speed"] = clamped
        body: dict[str, Any] = {"text": text, "model_id": model}
        if settings:
            body["voice_settings"] = settings
        language = opts.get("language_code")
        if language is None and lang and model in LANGUAGE_CODE_MODELS:
            language = lang.split("-")[0].split("_")[0].lower()
        if language:
            body["language_code"] = str(language)
        if opts.get("seed") is not None:
            body["seed"] = int(opts["seed"])
        url = (f"{self.base_url}/v1/text-to-speech/{urllib.parse.quote(voice_id, safe='')}"
               f"?output_format={OUTPUT_FORMAT}")
        return url, body

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        url, body = self.build_request(text, voice, lang, speed)
        key = self._key()
        data = self._request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"xi-api-key": key, "Content-Type": "application/json",
                     "Accept": "audio/pcm"},
            secrets=(key,),
        )
        return self._to_audio(data, text)
