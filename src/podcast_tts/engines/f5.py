"""Motor F5-TTS (clonación de voz a partir de ref.wav + ref.txt).

- Inglés (y cualquier ``lang`` "en"): modelo oficial ``F5TTS_v1_Base``.
- Castellano (``lang == "es"``): finetune comunitario ``jpgallegoar/F5-Spanish``
  (arquitectura ``F5TTS_Base``, licencia CC-BY-NC-4.0), descargado con
  ``cached_path`` a la caché de Hugging Face.
- Otros idiomas: no soportados (el modelo base solo conoce inglés y chino);
  se lanza :class:`EngineError` recomendando XTTS.

Los modelos se cargan de forma perezosa en la primera síntesis que los
necesita y se comparten entre instancias (uno por proceso). Ambos caben a la
vez en VRAM (~2 GB cada uno).
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

# clave -> (model cfg, ckpt hf://, vocab hf://)
_MODEL_SPECS: dict[str, tuple[str, str, str]] = {
    "en": ("F5TTS_v1_Base", "", ""),
    "es": (
        "F5TTS_Base",
        "hf://jpgallegoar/F5-Spanish/model_1250000.safetensors",
        "hf://jpgallegoar/F5-Spanish/vocab.txt",
    ),
}

_models: dict[str, Any] = {}  # clave -> f5_tts.api.F5TTS
_lock = threading.Lock()


def loaded_models() -> list[str]:
    """Claves ("es", "en") de los modelos F5 ya cargados en este proceso."""
    return sorted(_models)


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_model(key: str) -> Any:
    """Carga (una sola vez por proceso) el modelo F5 para ``key``."""
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
            with contextlib.redirect_stdout(io.StringIO()):  # f5_tts imprime rutas/vocab al cargar
                model = F5TTS(model=model_name, ckpt_file=ckpt, vocab_file=vocab, device=_device())
        except ImportError as exc:
            raise EngineError(f"F5-TTS no está instalado ({exc}). Ejecuta scripts/setup.ps1.") from exc
        except Exception as exc:  # descarga, CUDA, ficheros corruptos...
            raise EngineError(
                f"no se pudo cargar el modelo F5-TTS '{model_name}' para '{key}': {exc}"
            ) from exc
        log.info("F5-TTS: modelo %s (%s) cargado en %.1f s", model_name, key, time.perf_counter() - t0)
        _models[key] = model
        return model


def _silent(*_a: Any, **_k: Any) -> None:
    return None


_transcripts: dict[tuple[str, int, int], str] = {}


def _transcribe_reference(ref_wav: str, lang: str) -> str:
    """Transcribe la referencia con Whisper (lo que haría F5 con ``ref_text=""``).

    F5 pasa la *ruta* al pipeline ASR de transformers, que en este entorno intenta
    decodificarla con torchcodec y falla en Windows (DLL de FFmpeg compartidas).
    Aquí se transcribe el clip ya preprocesado por F5 (recortado a ~12 s) como
    array numpy y con torchcodec desactivado para el pipeline. Se cachea por clip.
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
            f"no se pudo transcribir automáticamente {ref_wav} con Whisper: {exc}. "
            "Escribe la transcripción exacta en ref.txt."
        ) from exc
    text = (text or "").strip()
    if not text:
        raise EngineError(f"Whisper no reconoció texto en {ref_wav}; añade ref.txt a mano.")
    log.warning("Transcripción automática de %s: %r", ref_wav, text)
    _transcripts[key] = text
    return text


class F5Engine:
    """Motor F5-TTS.

    Parámetros:
        seed: semilla para reproducibilidad (``None`` = aleatoria en cada frase).
        nfe_step: pasos del ODE (32 por defecto; más = más calidad y más lento).
        cross_fade_duration: crossfade entre lotes internos de F5.
        empty_cache: llama a ``torch.cuda.empty_cache()`` tras cada síntesis.
        preload: carga ya los modelos indicados (p.ej. ``("es", "en")``).
    """

    name = "f5"
    license_info = LicenseInfo(
        name="CC-BY-NC-4.0",
        url="https://creativecommons.org/licenses/by-nc/4.0/",
        commercial_use=False,
        notes="Pesos de F5TTS_v1_Base (SWivid/F5-TTS) y jpgallegoar/F5-Spanish: solo uso no "
              "comercial y con atribución. El código de F5-TTS es MIT, pero los pesos no.",
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

    @staticmethod
    def _model_key(lang: str) -> str:
        code = (lang or "").lower().split("-")[0].split("_")[0]
        if code not in SUPPORTED_LANGS:
            raise EngineError(
                f"F5-TTS solo admite castellano (es) e inglés (en); el idioma '{lang}' no está "
                "soportado. Usa el motor xtts (engine=xtts) para ese idioma."
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
                f"la voz '{voice.name}' no tiene clip de referencia ({voice.ref_wav}); F5-TTS lo "
                "necesita. Añade un ref.wav o usa el motor xtts con un speaker integrado."
            )
        ref_text = voice.ref_text
        if not ref_text:
            log.warning(
                "La voz '%s' no tiene ref.txt: F5-TTS transcribirá el clip con Whisper "
                "(descarga ~1.6 GB la primera vez y es menos fiable). Añade la transcripción exacta.",
                voice.name,
            )
            ref_text = _transcribe_reference(str(voice.ref_wav), voice.lang or key)
        speed = float(speed) if speed and speed > 0 else 1.0
        seed = self.seed if seed is None else seed

        model = _load_model(key)
        import torch

        try:
            # redirect_stdout: infer_process hace print() de ref_text/gen_text en cada lote
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
                f"F5-TTS falló al sintetizar con la voz '{voice.name}' ({lang}): {exc}"
            ) from exc
        finally:
            if self.empty_cache and torch.cuda.is_available():
                gc.collect()
                torch.cuda.empty_cache()

        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            raise EngineError(f"F5-TTS devolvió audio vacío para: {text[:60]!r}")
        return np.clip(audio, -1.0, 1.0)
