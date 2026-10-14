"""XTTS v2 engine (Coqui, idiap ``coqui-tts`` fork): built-in speaker or cloning from ref.wav.

- If the voice defines ``xtts_speaker``, that built-in speaker is used (58 available,
  see :data:`podcast_tts.voices.XTTS_BUILTIN_SPEAKERS`); otherwise it is cloned from
  ``voice.ref_wav`` (6-15 s).
- 17 languages (:data:`XTTS_LANGUAGES`); "zh" is mapped to "zh-cn".
- The model (~1.8 GB, non-commercial CPML license) is downloaded the first time to
  ``%LOCALAPPDATA%\\tts`` and loaded lazily only once per process.
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
    """``True`` if the XTTS model is already loaded in this process."""
    return _model is not None


def normalize_lang(lang: str) -> str:
    """Normalize the language code for XTTS or raise :class:`EngineError`."""
    code = (lang or "").strip().lower().replace("_", "-")
    code = _LANG_ALIASES.get(code, code)
    if code not in XTTS_LANGUAGES:
        base = code.split("-")[0]
        code = _LANG_ALIASES.get(base, base)
    if code not in XTTS_LANGUAGES:
        raise EngineError(
            f"XTTS v2 does not support language '{lang}'. Valid languages: {', '.join(XTTS_LANGUAGES)}"
        )
    return code


def _load_model() -> Any:
    global _model
    with _lock:
        if _model is not None:
            return _model
        # Accept the CPML license without a prompt (otherwise input() hangs non-interactive processes).
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        t0 = time.perf_counter()
        try:
            from TTS.api import TTS

            from ..device import select_device

            device = select_device("XTTS v2")
            _model = TTS(MODEL_NAME, progress_bar=False).to(device)
        except ImportError as exc:
            raise EngineError(f"coqui-tts is not installed ({exc}). Run bats/install.bat.") from exc
        except Exception as exc:
            raise EngineError(f"could not load the XTTS v2 model: {exc}") from exc
        log.info("XTTS v2 loaded in %.1f s", time.perf_counter() - t0)
        return _model


class XTTSEngine:
    """XTTS v2 engine.

    Parameters:
        temperature: sampling randomness (0.75 by default in XTTS; ``None`` = default).
        empty_cache: call ``torch.cuda.empty_cache()`` after each synthesis.
        preload: load the model right away in the constructor.
    """

    name = "xtts"
    license_info = LicenseInfo(
        name="Coqui Public Model License 1.0.0",
        url="https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt",
        commercial_use=False,
        notes="XTTS v2 weights: non-commercial use only (CPML). Coqui no longer sells commercial "
              "licenses. The coqui-tts code is MPL-2.0, but the weights are not.",
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

    @property
    def cache_tag(self) -> str:
        """Model, coqui-tts version and temperature."""
        from .base import package_version

        return f"xtts|{MODEL_NAME}|coqui-tts={package_version('coqui-tts')}|temp={self.temperature}"

    @staticmethod
    def speakers() -> list[str]:
        """Built-in speakers (loads the model)."""
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
                    f"voice '{voice.name}' has neither an xtts_speaker nor a reference clip "
                    f"({voice.ref_wav})."
                )
            speaker_wav = str(voice.ref_wav)
        speed = float(speed) if speed and speed > 0 else 1.0

        model = _load_model()
        if speaker and model.speakers and speaker not in model.speakers:
            raise EngineError(
                f"built-in speaker '{speaker}' of voice '{voice.name}' does not exist in XTTS v2 "
                "(see podcast_tts.voices.list_xtts_speakers())."
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
                f"XTTS v2 failed to synthesize with voice '{voice.name}' ({who}, {language}): {exc}"
            ) from exc
        finally:
            if self.empty_cache and torch.cuda.is_available():
                gc.collect()
                torch.cuda.empty_cache()

        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise EngineError(f"XTTS v2 returned empty audio for: {text[:60]!r}")
        return np.clip(audio, -1.0, 1.0)
