"""Verifica el entorno: Python, CUDA/GPU, ffmpeg y que F5-TTS y XTTS (coqui-tts) importan.

Uso:  .venv\Scripts\python.exe scripts\check_env.py
Codigo de salida 0 si todo esta OK, 1 si algo falla. No descarga modelos.
"""
from __future__ import annotations

import importlib.metadata as md
import os
import shutil
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("COQUI_TOS_AGREED", "1")

ok = True


def report(name: str, passed: bool, detail: str = "") -> None:
    global ok
    ok &= passed
    print(f"[{'OK' if passed else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def version(pkg: str) -> str:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return "no instalado"


report("Python 3.11", sys.version_info[:2] == (3, 11), sys.version.split()[0])
report("ffmpeg en PATH", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "no encontrado (pydub lo necesita)")

try:
    import torch
    import torchaudio

    cuda = torch.cuda.is_available()
    gpu = torch.cuda.get_device_name(0) if cuda else "sin GPU"
    report("torch CUDA", cuda, f"torch {torch.__version__}, CUDA {torch.version.cuda}, {gpu}")
    backends = torchaudio.list_audio_backends()
    report("torchaudio backend soundfile", "soundfile" in backends, f"torchaudio {torchaudio.__version__}, backends={backends}")
except Exception as e:  # noqa: BLE001
    report("torch", False, repr(e))

try:
    from f5_tts.api import F5TTS  # noqa: F401

    report("F5-TTS importa", True, f"f5-tts {version('f5-tts')}")
except Exception as e:  # noqa: BLE001
    report("F5-TTS importa", False, repr(e))

try:
    from TTS.api import TTS  # noqa: F401

    report("XTTS (coqui-tts) importa", True, f"coqui-tts {version('coqui-tts')}, transformers {version('transformers')}")
except Exception as e:  # noqa: BLE001
    report("XTTS (coqui-tts) importa", False, repr(e))

for pkg in ("gradio", "pydub", "soundfile", "numpy"):
    report(f"{pkg}", version(pkg) != "no instalado", version(pkg))

print("\nTODO OK" if ok else "\nHAY ERRORES")
sys.exit(0 if ok else 1)
