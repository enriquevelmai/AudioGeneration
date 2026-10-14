"""Selection of the compute device (CUDA GPU or CPU) for the local engines.

By default ``cuda`` is used if PyTorch sees an NVIDIA GPU, otherwise ``cpu``.
The ``PODCAST_TTS_DEVICE`` environment variable (``cpu`` | ``cuda`` | ``auto``)
forces the choice. ``torch`` is only imported when the function is called.
"""

from __future__ import annotations

import logging
import os

__all__ = ["DEVICE_ENV", "select_device"]

log = logging.getLogger(__name__)

DEVICE_ENV = "PODCAST_TTS_DEVICE"
_warned: set[str] = set()


def select_device(engine: str = "") -> str:
    """Return ``"cuda"`` or ``"cpu"`` depending on the available GPU and ``PODCAST_TTS_DEVICE``.

    Raises :class:`RuntimeError` if ``cuda`` is forced and PyTorch cannot see it.
    Warns (once per engine) when synthesis is going to run on the CPU.
    """
    import torch

    wanted = os.environ.get(DEVICE_ENV, "").strip().lower() or "auto"
    if wanted not in ("auto", "cpu", "cuda"):
        log.warning("%s=%r is not valid (use cpu, cuda or auto); choosing automatically.",
                    DEVICE_ENV, wanted)
        wanted = "auto"
    cuda_ok = torch.cuda.is_available()
    if wanted == "cuda" and not cuda_ok:
        raise RuntimeError(
            f"{DEVICE_ENV}=cuda but PyTorch cannot see any CUDA GPU (torch {torch.__version__}). "
            "Install the CUDA build with bats\\install_gpu.bat or unset the variable."
        )
    device = "cuda" if (wanted == "cuda" or (wanted == "auto" and cuda_ok)) else "cpu"
    if device == "cpu" and engine not in _warned:
        _warned.add(engine)
        why = f"forced with {DEVICE_ENV}=cpu" if wanted == "cpu" else "no CUDA GPU available"
        log.warning(
            "%s will run on the CPU (%s): synthesis will be VERY slow (roughly 10-50 times "
            "slower than on an NVIDIA GPU).", engine or "The engine", why,
        )
    return device
