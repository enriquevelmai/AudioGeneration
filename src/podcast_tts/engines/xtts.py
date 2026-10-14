"""Motor XTTS v2 (Coqui, fork idiap ``coqui-tts``): speaker integrado o clonación con ref.wav.

- Si la voz define ``xtts_speaker`` se usa ese speaker integrado (58 disponibles,
  ver :data:`podcast_tts.voices.XTTS_BUILTIN_SPEAKERS`); si no, se clona con
  ``voice.ref_wav`` (6-15 s).
- 17 idiomas (:data:`XTTS_LANGUAGES`); "zh" se mapea a "zh-cn".
- El modelo (~1.8 GB, licencia CPML no comercial) se descarga la primera vez a
  ``%LOCALAPPDATA%\\tts`` y se carga de forma perezosa una sola vez por proceso.
"""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import EngineError, LicenseInfo

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["XTTSEngine", "XTTS_LANGUAGES", "MODEL_NAME", "is_loaded", "normalize_lang"]

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_LANGUAGES: tuple[str, ...] = (
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "hu", "ko",
    "ja", "hi",
)
_LANG_ALIASES = {"zh": "zh-cn", "zh_cn": "zh-cn", "zh-hans": "zh-cn"}

_model: Any = None  # TTS.api.TTS
_lock = threading.Lock()


def is_loaded() -> bool:
    """``True`` si el modelo XTTS ya está cargado en este proceso."""
    return _model is not None


def normalize_lang(lang: str) -> str:
    """Normaliza el código de idioma para XTTS o lanza :class:`EngineError`."""
    code = (lang or "").strip().lower().replace("_", "-")
    code = _LANG_ALIASES.get(code, code)
    if code not in XTTS_LANGUAGES:
        base = code.split("-")[0]
        code = _LANG_ALIASES.get(base, base)
    if code not in XTTS_LANGUAGES:
        raise EngineError(
            f"XTTS v2 no admite el idioma '{lang}'. Idiomas válidos: {', '.join(XTTS_LANGUAGES)}"
        )
    return code


def _load_model() -> Any:
    global _model
    with _lock:
        if _model is not None:
            return _model
        # Acepta la licencia CPML sin prompt (si no, input() cuelga procesos no interactivos).
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        t0 = time.perf_counter()
        try:
            from TTS.api import TTS

            from ..device import select_device

            device = select_device("XTTS v2")
            _model = TTS(MODEL_NAME, progress_bar=False).to(device)
        except ImportError as exc:
            raise EngineError(f"coqui-tts no está instalado ({exc}). Ejecuta bats\install.bat.") from exc
        except Exception as exc:
            raise EngineError(f"no se pudo cargar el modelo XTTS v2: {exc}") from exc
        log.info("XTTS v2 cargado en %.1f s", time.perf_counter() - t0)
        return _model


class XTTSEngine:
    """Motor XTTS v2.

    Parámetros:
        temperature: aleatoriedad del muestreo (0.75 por defecto en XTTS; ``None`` = por defecto).
        empty_cache: llama a ``torch.cuda.empty_cache()`` tras cada síntesis.
        preload: carga el modelo ya en el constructor.
    """

    name = "xtts"
    license_info = LicenseInfo(
        name="Coqui Public Model License 1.0.0",
        url="https://coqui.ai/cpml",
        commercial_use=False,
        notes="Pesos de XTTS v2: solo uso no comercial (CPML). Coqui ya no vende licencias "
              "comerciales. El código de coqui-tts es MPL-2.0, pero los pesos no.",
    )

    def __init__(
        self,
        temperature: float | None = None,
        empty_cache: bool = False,
        preload: bool = False,
    ) -> None:
        self.temperature = temperature
        self.empty_cache = empty_cache
        if preload:
            _load_model()

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @staticmethod
    def speakers() -> list[str]:
        """Speakers integrados (carga el modelo)."""
        return list(_load_model().speakers or [])

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        language = normalize_lang(lang)
        speaker = voice.xtts_speaker or None
        speaker_wav = None
        if not speaker:
            if not voice.has_ref:
                raise EngineError(
                    f"la voz '{voice.name}' no tiene ni xtts_speaker ni clip de referencia "
                    f"({voice.ref_wav})."
                )
            speaker_wav = str(voice.ref_wav)
        speed = float(speed) if speed and speed > 0 else 1.0

        model = _load_model()
        if speaker and model.speakers and speaker not in model.speakers:
            raise EngineError(
                f"el speaker integrado '{speaker}' de la voz '{voice.name}' no existe en XTTS v2 "
                "(ver podcast_tts.voices.list_xtts_speakers())."
            )
        kwargs: dict[str, Any] = {"speed": speed}
        if self.temperature is not None:
            kwargs["temperature"] = float(self.temperature)

        import torch

        try:
            with torch.inference_mode():
                wav = model.tts(
                    text=text,
                    speaker=speaker,
                    speaker_wav=speaker_wav,
                    language=language,
                    split_sentences=True,
                    **kwargs,
                )
        except EngineError:
            raise
        except Exception as exc:
            who = f"speaker '{speaker}'" if speaker else f"clip {speaker_wav}"
            raise EngineError(
                f"XTTS v2 falló al sintetizar con la voz '{voice.name}' ({who}, {language}): {exc}"
            ) from exc
        finally:
            if self.empty_cache and torch.cuda.is_available():
                gc.collect()
                torch.cuda.empty_cache()

        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise EngineError(f"XTTS v2 devolvió audio vacío para: {text[:60]!r}")
        return np.clip(audio, -1.0, 1.0)
