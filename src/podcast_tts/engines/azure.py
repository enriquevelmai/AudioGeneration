"""Motor Azure AI Speech (API REST de pago con clave propia; solo stdlib).

``POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1`` con la cabecera
``Ocp-Apim-Subscription-Key`` y un cuerpo SSML. Formato ``raw-24khz-16bit-mono-pcm``.

No tiene nada que ver con Edge-TTS (servicio gratuito no oficial, bloqueado y no
usado en este proyecto): aquí se usa un recurso de Azure propio con su clave.

Voz: ``provider_voice_id`` = nombre de la voz neural (p.ej. ``es-ES-AlvaroNeural``).
``provider_options`` admite ``xml_lang`` (locale del SSML), ``style`` y ``style_degree``
(``mstts:express-as``), ``role`` y ``pitch`` (p.ej. ``"+5%"``).

Claves: ``AZURE_SPEECH_KEY`` y ``AZURE_SPEECH_REGION`` (entorno o ``.env``).
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
    """SSML con ``xml:lang``, la voz y ``prosody rate`` (si ``speed != 1``)."""
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
    # Voces multilingües: si el segmento está en otro idioma, se indica con <lang>.
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
    """Motor Azure AI Speech (texto a voz neural).

    Parámetros (además de los de :class:`CloudEngine`):
        region: región del recurso (si no, ``AZURE_SPEECH_REGION``).
        endpoint: URL completa alternativa (p.ej. nubes soberanas o contenedores).
    """

    name = "azure"
    provider = "Azure AI Speech"
    key_env = "AZURE_SPEECH_KEY"
    required_config = ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION")
    license_info = LicenseInfo(
        name="Microsoft Product Terms (Azure AI Speech)",
        url="https://www.microsoft.com/licensing/terms/productoffering/MicrosoftAzure",
        commercial_use=True,
        notes="Uso comercial permitido con una suscripción de Azure propia, sujeto a los "
              "términos de Microsoft y al código de conducta de Azure AI Speech. "
              "No es Edge-TTS (que no se usa).",
    )

    def __init__(self, api_key: str | None = None, *, region: str | None = None,
                 endpoint: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self.region = region
        self.endpoint = endpoint

    def _url(self) -> str:
        if self.endpoint:
            return self.endpoint
        region = (self.region or self._require("AZURE_SPEECH_REGION", "la región")).strip().lower()
        if not _REGION_RE.match(region):
            raise EngineError(f"región de Azure inválida {region!r} (p.ej. westeurope, eastus)")
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
