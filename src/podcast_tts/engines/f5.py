"""F5-TTS engine (voice cloning from ref.wav + ref.txt).

- English (and any "en" ``lang``): official ``F5TTS_v1_Base`` model.
- Spanish (``lang == "es"``): community finetune ``jpgallegoar/F5-Spanish``
  (``F5TTS_Base`` architecture, CC-BY-NC-4.0 license), downloaded with
  ``cached_path`` into the Hugging Face cache.
- Other languages: not supported (the base model only knows English and Chinese);
  :class:`EngineError` is raised recommending XTTS.

Models are loaded lazily on the first synthesis that needs them and are
shared between instances (one per process). Both fit in VRAM at the same
time (~2 GB each).
"""

from __future__ import annotations

import contextlib
import gc
import io
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import EngineError, LicenseInfo

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["F5Engine", "SUPPORTED_LANGS", "loaded_models"]

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
SUPPORTED_LANGS = ("es", "en")

# key -> (model cfg, ckpt hf://, vocab hf://)
_MODEL_SPECS: dict[str, tuple[str, str, str]] = {
    "en": ("F5TTS_v1_Base", "", ""),
    "es": (
        "F5TTS_Base",
        "hf://jpgallegoar/F5-Spanish/model_1250000.safetensors",
        "hf://jpgallegoar/F5-Spanish/vocab.txt",
    ),
}

_models: dict[str, Any] = {}  # key -> f5_tts.api.F5TTS
_lock = threading.Lock()


def loaded_models() -> list[str]:
    """Keys ("es", "en") of the F5 models already loaded in this process."""
    return sorted(_models)


def _device() -> str:
    from ..device import select_device

    return select_device("F5-TTS")


def _load_model(key: str) -> Any:
    """Load (only once per process) the F5 model for ``key``."""
    with _lock:
        if key in _models:
            return _models[key]
        model_name, ckpt_uri, vocab_uri = _MODEL_SPECS[key]
        t0 = time.perf_counter()
        try:
            from f5_tts.api import F5TTS

            ckpt = vocab = ""
            if ckpt_uri:
                from cached_path import cached_path

                ckpt = str(cached_path(ckpt_uri))
                vocab = str(cached_path(vocab_uri))
            with contextlib.redirect_stdout(io.StringIO()):  # f5_tts prints paths/vocab while loading
                model = F5TTS(model=model_name, ckpt_file=ckpt, vocab_file=vocab, device=_device())
        except ImportError as exc:
            raise EngineError(f"F5-TTS is not installed ({exc}). Run bats/install.bat.") from exc
        except Exception as exc:  # download, CUDA, corrupt files...
            raise EngineError(
                f"could not load F5-TTS model '{model_name}' for '{key}': {exc}"
            ) from exc
        log.info("F5-TTS: model %s (%s) loaded in %.1f s", model_name, key, time.perf_counter() - t0)
        _models[key] = model
        return model


def _silent(*_a: Any, **_k: Any) -> None:
    return None


_transcripts: dict[tuple[str, int, int], str] = {}


def _transcribe_reference(ref_wav: str, lang: str) -> str:
    """Transcribe the reference with Whisper (what F5 would do with ``ref_text=""``).

    F5 passes the *path* to the transformers ASR pipeline, which in this environment
    tries to decode it with torchcodec and fails on Windows (shared FFmpeg DLLs).
    Here the clip already preprocessed by F5 (trimmed to ~12 s) is transcribed as a
    numpy array with torchcodec disabled for the pipeline. Cached per clip.
    """
    import os

    st = os.stat(ref_wav)
    key = (os.path.abspath(ref_wav), st.st_size, int(st.st_mtime))
    if key in _transcripts:
        return _transcripts[key]
    try:
        import soundfile as sf
        import transformers.pipelines.automatic_speech_recognition as asr_mod
        from f5_tts.infer.utils_infer import preprocess_ref_audio_text, transcribe

        asr_mod.is_torchcodec_available = lambda: False  # type: ignore[attr-defined]
        with contextlib.redirect_stdout(io.StringIO()):
            processed, _ = preprocess_ref_audio_text(ref_wav, "-", show_info=_silent)
        audio, sr = sf.read(processed, dtype="float32", always_2d=True)
        text = transcribe({"raw": audio.mean(axis=1), "sampling_rate": sr}, lang or None)
    except Exception as exc:
        raise EngineError(
            f"could not automatically transcribe {ref_wav} with Whisper: {exc}. "
            "Write the exact transcript in ref.txt."
        ) from exc
    text = (text or "").strip()
    if not text:
        raise EngineError(f"Whisper recognized no text in {ref_wav}; add ref.txt by hand.")
    log.warning("Automatic transcript of %s: %r", ref_wav, text)
    _transcripts[key] = text
    return text


class F5Engine:
    """F5-TTS engine.

    Parameters:
        seed: seed for reproducibility (``None`` = random for each sentence).
        nfe_step: ODE steps (32 by default; more = higher quality and slower).
        cross_fade_duration: crossfade between F5's internal batches.
        empty_cache: call ``torch.cuda.empty_cache()`` after each synthesis.
        preload: load the given models right away (e.g. ``("es", "en")``).
    """

    name = "f5"
    license_info = LicenseInfo(
        name="CC-BY-NC-4.0",
        url="https://creativecommons.org/licenses/by-nc/4.0/",
        commercial_use=False,
        notes="F5TTS_v1_Base (SWivid/F5-TTS) and jpgallegoar/F5-Spanish weights: non-commercial "
              "use only, with attribution. The F5-TTS code is MIT, but the weights are not.",
    )

    def __init__(
        self,
        seed: int | None = None,
        nfe_step: int = 32,
        cross_fade_duration: float = 0.15,
        empty_cache: bool = False,
        preload: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.seed = seed
        self.nfe_step = int(nfe_step)
        self.cross_fade_duration = float(cross_fade_duration)
        self.empty_cache = empty_cache
        for key in preload:
            _load_model(self._model_key(key))

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def cache_tag(self) -> str:
        """Models (cfg + checkpoint), f5-tts version and inference parameters."""
        from .base import package_version

        models = ";".join(f"{k}={m}:{c}" for k, (m, c, _v) in sorted(_MODEL_SPECS.items()))
        return (f"f5|{models}|f5-tts={package_version('f5-tts')}|nfe={self.nfe_step}"
                f"|xfade={self.cross_fade_duration:g}|seed={self.seed}")

    @staticmethod
    def _model_key(lang: str) -> str:
        code = (lang or "").lower().split("-")[0].split("_")[0]
        if code not in SUPPORTED_LANGS:
            raise EngineError(
                f"F5-TTS only supports Spanish (es) and English (en); language '{lang}' is not "
                "supported. Use the xtts engine (engine=xtts) for that language."
            )
        return code

    def synthesize(
        self,
        text: str,
        voice: "Voice",
        lang: str,
        speed: float = 1.0,
        *,
        seed: int | None = None,
    ) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        key = self._model_key(lang)
        if not voice.has_ref:
            raise EngineError(
                f"voice '{voice.name}' has no reference clip ({voice.ref_wav}); F5-TTS needs "
                "one. Add a ref.wav or use the xtts engine with a built-in speaker."
            )
        ref_text = voice.ref_text
        if not ref_text:
            log.warning(
                "Voice '%s' has no ref.txt: F5-TTS will transcribe the clip with Whisper "
                "(downloads ~1.6 GB the first time and is less reliable). Add the exact transcript.",
                voice.name,
            )
            ref_text = _transcribe_reference(str(voice.ref_wav), voice.lang or key)
        speed = float(speed) if speed and speed > 0 else 1.0
        seed = self.seed if seed is None else seed

        model = _load_model(key)
        import torch

        try:
            # redirect_stdout: infer_process print()s ref_text/gen_text on every batch
            with torch.inference_mode(), contextlib.redirect_stdout(io.StringIO()):
                wav, _sr, _spec = model.infer(
                    ref_file=str(voice.ref_wav),
                    ref_text=ref_text,
                    gen_text=text,
                    nfe_step=self.nfe_step,
                    cross_fade_duration=self.cross_fade_duration,
                    speed=speed,
                    seed=seed,
                    show_info=_silent,
                    progress=None,
                )
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(
                f"F5-TTS failed to synthesize with voice '{voice.name}' ({lang}): {exc}"
            ) from exc
        finally:
            if self.empty_cache and torch.cuda.is_available():
                gc.collect()
                torch.cuda.empty_cache()

        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise EngineError(f"F5-TTS returned empty audio for: {text[:60]!r}")
        return np.clip(audio, -1.0, 1.0)
