"""Verifica el entorno de podcast-tts por capas, con o sin extras instalados.

Capas:
  - núcleo  (siempre): Python 3.11, ffmpeg, numpy, pydub, gradio, pyyaml, scipy, pyloudnorm, huggingface-hub
  - local   (extra `local`): torch/torchaudio 2.8, F5-TTS y XTTS (coqui-tts) importan
  - cuda | cpu (variante de torch): con cuda, además, que PyTorch vea la GPU

Uso:  .venv\\Scripts\\python.exe scripts\\check_env.py
Código de salida 0 si lo instalado es coherente (p.ej. solo núcleo es válido), 1 si algo falla.
No descarga modelos (para eso: `podcast-tts models status|download`).
"""
from __future__ import annotations

import importlib.metadata as md
import importlib.util
import os
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("COQUI_TOS_AGREED", "1")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
EXTRAS_FILE = ROOT / ".venv" / "podcast-tts-extras.txt"
ok = True


def report(name: str, passed: bool, detail: str = "", warn_only: bool = False) -> None:
    global ok
    if not passed and not warn_only:
        ok = False
    tag = "OK" if passed else ("AVISO" if warn_only else "FAIL")
    print(f"[{tag}] {name}" + (f": {detail}" if detail else ""))


def version(pkg: str) -> str | None:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def section(title: str) -> None:
    print(f"\n== {title} ==")


# --------------------------------------------------------------------------- núcleo
section("Núcleo")
report("Python 3.11", sys.version_info[:2] == (3, 11), sys.version.split()[0])
ffmpeg = shutil.which("ffmpeg")
report("ffmpeg en PATH", ffmpeg is not None, ffmpeg or "no encontrado (pydub lo necesita para MP3)")
for pkg in ("numpy", "pydub", "gradio", "pyyaml", "scipy", "pyloudnorm", "huggingface-hub"):
    v = version(pkg)
    report(pkg, v is not None, v or "no instalado")
try:
    import podcast_tts  # noqa: F401
    from podcast_tts.engines import get_engine

    get_engine("dummy")
    report("podcast_tts importa (motor dummy)", True, f"podcast-tts {version('podcast-tts') or '?'}")
except Exception as e:  # noqa: BLE001
    report("podcast_tts importa", False, repr(e))
report("el núcleo no importa torch", "torch" not in sys.modules,
       "" if "torch" not in sys.modules else "algún módulo del núcleo importa torch al cargarse")

# --------------------------------------------------------------------------- capas
recorded = EXTRAS_FILE.read_text(encoding="utf-8").split() if EXTRAS_FILE.is_file() else None
torch_v = version("torch")
local_pkgs = {p: version(p) for p in ("f5-tts", "coqui-tts", "transformers")}
has_local = any(local_pkgs.values()) or (recorded is not None and "local" in recorded)

if torch_v is None:
    variant = None
elif "+cu" in torch_v:
    variant = "cuda"
elif "+cpu" in torch_v:
    variant = "cpu"
else:
    variant = "pypi"  # torch de PyPI (sin --extra cuda/cpu): CPU en Windows

section("Capas instaladas")
layers = ["núcleo"] + (["local"] if has_local else []) + ([variant] if variant else [])
print("Detectadas: " + " + ".join(layers))
if recorded is not None:
    print(f"Registradas por el instalador ({EXTRAS_FILE.name}): {' '.join(recorded) or '(ninguna)'}")
    expected = {e for e in recorded if e in ("cuda", "cpu")}
    if expected and variant not in expected:
        report("variante de torch", False,
               f"el instalador registró {'/'.join(expected)} pero torch es {torch_v or 'no instalado'}")

if has_local:
    section("Motores locales (extra local)")
    if torch_v is None:
        report("torch", False, "falta torch: ejecuta bats\\install.bat (o uv sync --extra local --extra cuda|cpu)")
    else:
        try:
            import torch
            import torchaudio

            report("torch 2.8", torch.__version__.startswith("2.8."), f"torch {torch.__version__}")
            backends = torchaudio.list_audio_backends()
            report("torchaudio backend soundfile", "soundfile" in backends,
                   f"torchaudio {torchaudio.__version__}, backends={backends}")
            if variant == "cuda":
                cuda = torch.cuda.is_available()
                gpu = torch.cuda.get_device_name(0) if cuda else "PyTorch no ve ninguna GPU"
                report("CUDA disponible", cuda, f"CUDA {torch.version.cuda}, {gpu}")
            else:
                report("dispositivo", True, "CPU (sin variante CUDA): la síntesis será lenta", )
        except Exception as e:  # noqa: BLE001
            report("torch", False, repr(e))
    for pkg in ("f5-tts", "coqui-tts", "transformers"):
        report(f"{pkg} instalado", local_pkgs[pkg] is not None, local_pkgs[pkg] or "no instalado")
    try:
        from f5_tts.api import F5TTS  # noqa: F401

        report("F5-TTS importa", True)
    except Exception as e:  # noqa: BLE001
        report("F5-TTS importa", False, repr(e))
    try:
        from TTS.api import TTS  # noqa: F401

        report("XTTS (coqui-tts) importa", True)
    except Exception as e:  # noqa: BLE001
        report("XTTS (coqui-tts) importa", False, repr(e))
else:
    section("Motores locales")
    print("Extra `local` no instalado: solo el motor dummy. Para F5/XTTS: bats\\install.bat")
    if torch_v is not None:
        report("torch sin motores", True, f"torch {torch_v} instalado pero sin el extra local", warn_only=True)

# --------------------------------------------------------------------------- modelos (informativo)
if has_local:
    section("Modelos (informativo)")
    try:
        from podcast_tts.models import MODELS, model_status

        for m in MODELS:
            st = model_status(m)
            state = "descargado" if st["downloaded"] else "no descargado (se bajará al usarlo)"
            print(f"  {m.name:<11} {state}")
    except Exception as e:  # noqa: BLE001
        report("estado de modelos", False, repr(e), warn_only=True)

print("\nTODO OK" if ok else "\nHAY ERRORES")
sys.exit(0 if ok else 1)
