"""Azure AI Speech engine (paid REST API with your own key; stdlib only).

``POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1`` with the
``Ocp-Apim-Subscription-Key`` header and an SSML body. Format ``raw-24khz-16bit-mono-pcm``.

It has nothing to do with Edge-TTS (an unofficial free service, blocked and not
used in this project): this uses your own Azure resource with its key.

Voice: ``provider_voice_id`` = neural voice name (e.g. ``es-ES-AlvaroNeural``).
``provider_options`` accepts ``xml_lang`` (SSML locale), ``style`` and ``style_degree``
(``mstts:express-as``), ``role`` and ``pitch`` (e.g. ``"+5%"``).

Keys: ``AZURE_SPEECH_KEY`` and ``AZURE_SPEECH_REGION`` (environment or ``.env``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from .base import EngineError, LicenseInfo
from .cloud import CloudEngine

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["AzureEngine", "OUTPUT_FORMAT", "build_ssml"]

OUTPUT_FORMAT = "raw-24khz-16bit-mono-pcm"
_REGION_RE = re.compile(r"^[a-z0-9]+$")
_LOCALE_RE = re.compile(r"^([a-z]{2,3}-[A-Z]{2})")
DEFAULT_LOCALES = {
    "es": "es-ES", "en": "en-US", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "pt": "pt-PT",
    "ca": "ca-ES", "gl": "gl-ES", "eu": "eu-ES", "nl": "nl-NL", "pl": "pl-PL", "ja": "ja-JP",
    "zh": "zh-CN", "ko": "ko-KR", "ru": "ru-RU", "ar": "ar-SA", "hi": "hi-IN", "tr": "tr-TR",
    "cs": "cs-CZ", "hu": "hu-HU",
}


def _locale(lang: str) -> str | None:
    code = (lang or "").strip().replace("_", "-")
    if not code:
        return None
    parts = code.split("-")
    if len(parts) >= 2:
        return f"{parts[0].lower()}-{parts[1].upper()}"
    return DEFAULT_LOCALES.get(parts[0].lower())


def _rate(speed: float) -> str | None:
    speed = float(speed) if speed and speed > 0 else 1.0
    if abs(speed - 1.0) < 1e-6:
        return None
    pct = round((speed - 1.0) * 100)
    return f"{pct:+d}%"


def build_ssml(text: str, voice_name: str, lang: str, speed: float = 1.0,
               options: dict[str, Any] | None = None) -> str:
    """SSML with ``xml:lang``, the voice and ``prosody rate`` (if ``speed != 1``)."""
    opts = options or {}
    m = _LOCALE_RE.match(voice_name)
    voice_locale = m.group(1) if m else None
    seg_locale = _locale(lang)
    xml_lang = opts.get("xml_lang") or voice_locale or seg_locale or "es-ES"
    inner = escape(text)
    prosody: list[str] = []
    rate = _rate(speed)
    if rate:
        prosody.append(f"rate={quoteattr(rate)}")
    if opts.get("pitch"):
        prosody.append(f"pitch={quoteattr(str(opts['pitch']))}")
    if prosody:
        inner = f"<prosody {' '.join(prosody)}>{inner}</prosody>"
    # Multilingual voices: if the segment is in another language, mark it with <lang>.
    if ("multilingual" in voice_name.lower() and seg_locale and voice_locale
            and seg_locale != voice_locale):
        inner = f"<lang xml:lang={quoteattr(seg_locale)}>{inner}</lang>"
    if opts.get("style") or opts.get("role"):
        attrs = []
        if opts.get("style"):
            attrs.append(f"style={quoteattr(str(opts['style']))}")
        if opts.get("style_degree") is not None:
            attrs.append(f"styledegree={quoteattr(str(opts['style_degree']))}")
        if opts.get("role"):
            attrs.append(f"role={quoteattr(str(opts['role']))}")
        inner = f"<mstts:express-as {' '.join(attrs)}>{inner}</mstts:express-as>"
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" '
        f"xml:lang={quoteattr(xml_lang)}>"
        f"<voice name={quoteattr(voice_name)}>{inner}</voice></speak>"
    )


class AzureEngine(CloudEngine):
    """Azure AI Speech engine (neural text to speech).

    Parameters (in addition to those of :class:`CloudEngine`):
        region: region of the resource (otherwise ``AZURE_SPEECH_REGION``).
        endpoint: alternative full URL (e.g. sovereign clouds or containers).
    """

    name = "azure"
    provider = "Azure AI Speech"
    key_env = "AZURE_SPEECH_KEY"
    required_config = ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION")
    license_info = LicenseInfo(
        name="Microsoft Product Terms (Azure AI Speech)",
        url="https://www.microsoft.com/licensing/terms/productoffering/MicrosoftAzure",
        commercial_use=True,
        notes="Commercial use allowed with your own Azure subscription, subject to "
              "Microsoft's terms and the Azure AI Speech code of conduct. "
              "This is not Edge-TTS (which is not used).",
    )

    def __init__(self, api_key: str | None = None, *, region: str | None = None,
                 endpoint: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self.region = region
        self.endpoint = endpoint

    @property
    def cache_tag(self) -> str:
        # Azure has no "model": the neural voice is in provider_voice_id (already in the fingerprint).
        return f"azure|{OUTPUT_FORMAT}"

    def _url(self) -> str:
        if self.endpoint:
            return self.endpoint
        region = (self.region or self._require("AZURE_SPEECH_REGION", "the region")).strip().lower()
        if not _REGION_RE.match(region):
            raise EngineError(f"invalid Azure region {region!r} (e.g. westeurope, eastus)")
        return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        voice_name = self._voice_id(voice)
        ssml = build_ssml(text, voice_name, lang, speed, self._options(voice))
        url = self._url()
        key = self._key()
        data = self._request(
            url,
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
            },
            secrets=(key,),
        )
        return self._to_audio(data, text)
