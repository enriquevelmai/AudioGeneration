"""Selección del dispositivo de cálculo (GPU CUDA o CPU) para los motores locales.

Por defecto se usa ``cuda`` si PyTorch ve una GPU NVIDIA y, si no, ``cpu``.
La variable de entorno ``PODCAST_TTS_DEVICE`` (``cpu`` | ``cuda`` | ``auto``)
fuerza la elección. Importa ``torch`` solo al llamarse.
"""

from __future__ import annotations

import logging
import os

__all__ = ["DEVICE_ENV", "select_device"]

log = logging.getLogger(__name__)

DEVICE_ENV = "PODCAST_TTS_DEVICE"
_warned: set[str] = set()


def select_device(engine: str = "") -> str:
    """Devuelve ``"cuda"`` o ``"cpu"`` según la GPU disponible y ``PODCAST_TTS_DEVICE``.

    Lanza :class:`RuntimeError` si se fuerza ``cuda`` y PyTorch no la ve.
    Avisa (una vez por motor) cuando la síntesis va a ir por CPU.
    """
    import torch

    wanted = os.environ.get(DEVICE_ENV, "").strip().lower() or "auto"
    if wanted not in ("auto", "cpu", "cuda"):
        log.warning("%s=%r no es válido (usa cpu, cuda o auto); se elige automáticamente.",
                    DEVICE_ENV, wanted)
        wanted = "auto"
    cuda_ok = torch.cuda.is_available()
    if wanted == "cuda" and not cuda_ok:
        raise RuntimeError(
            f"{DEVICE_ENV}=cuda pero PyTorch no ve ninguna GPU CUDA (torch {torch.__version__}). "
            "Instala la variante CUDA con bats\\install_gpu.bat o quita la variable."
        )
    device = "cuda" if (wanted == "cuda" or (wanted == "auto" and cuda_ok)) else "cpu"
    if device == "cpu" and engine not in _warned:
        _warned.add(engine)
        why = f"forzado con {DEVICE_ENV}=cpu" if wanted == "cpu" else "no hay GPU CUDA disponible"
        log.warning(
            "%s se ejecutará en CPU (%s): la síntesis será MUY lenta (del orden de 10-50 veces "
            "más que en una GPU NVIDIA).", engine or "El motor", why,
        )
    return device
