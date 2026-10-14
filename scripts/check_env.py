"""Checks the podcast-tts environment layer by layer, with or without extras installed.

Layers:
  - core    (always): Python 3.11, ffmpeg, numpy, pydub, gradio, pyyaml, scipy, pyloudnorm, huggingface-hub
  - local   (`local` extra): torch/torchaudio 2.8, F5-TTS and XTTS (coqui-tts) import
  - cuda | cpu (torch variant): with cuda, also that PyTorch sees the GPU
  - desktop (`desktop` extra, optional): pywebview and the WebView2 runtime (warnings only)

Usage:  .venv\\Scripts\\python.exe scripts\\check_env.py
Exit code 0 if what is installed is consistent (e.g. core only is valid), 1 if something fails.
It does not download models (for that: `podcast-tts models status|download`).
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
    tag = "OK" if passed else ("WARN" if warn_only else "FAIL")
    print(f"[{tag}] {name}" + (f": {detail}" if detail else ""))


def version(pkg: str) -> str | None:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def section(title: str) -> None:
    print(f"\n== {title} ==")


# --------------------------------------------------------------------------- core
section("Core")
report("Python 3.11", sys.version_info[:2] == (3, 11), sys.version.split()[0])
ffmpeg = shutil.which("ffmpeg")
report("ffmpeg on PATH", ffmpeg is not None, ffmpeg or "not found (pydub needs it for MP3)")
for pkg in ("numpy", "pydub", "gradio", "pyyaml", "scipy", "pyloudnorm", "huggingface-hub"):
    v = version(pkg)
    report(pkg, v is not None, v or "not installed")
try:
    import podcast_tts  # noqa: F401
    from podcast_tts.engines import get_engine

    get_engine("dummy")
    report("podcast_tts imports (dummy engine)", True, f"podcast-tts {version('podcast-tts') or '?'}")
except Exception as e:  # noqa: BLE001
    report("podcast_tts imports", False, repr(e))
report("core does not import torch", "torch" not in sys.modules,
       "" if "torch" not in sys.modules else "some core module imports torch when loaded")

# --------------------------------------------------------------------------- layers
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
    variant = "pypi"  # torch from PyPI (without --extra cuda/cpu): CPU on Windows

section("Installed layers")
layers = ["core"] + (["local"] if has_local else []) + ([variant] if variant else [])
print("Detected: " + " + ".join(layers))
if recorded is not None:
    print(f"Recorded by the installer ({EXTRAS_FILE.name}): {' '.join(recorded) or '(none)'}")
    expected = {e for e in recorded if e in ("cuda", "cpu")}
    if expected and variant not in expected:
        report("torch variant", False,
               f"the installer recorded {'/'.join(expected)} but torch is {torch_v or 'not installed'}")

if has_local:
    section("Local engines (local extra)")
    if torch_v is None:
        report("torch", False, "torch is missing: run bats\\install.bat (or uv sync --extra local --extra cuda|cpu)")
    else:
        try:
            import torch
            import torchaudio

            report("torch 2.8", torch.__version__.startswith("2.8."), f"torch {torch.__version__}")
            backends = torchaudio.list_audio_backends()
            report("torchaudio soundfile backend", "soundfile" in backends,
                   f"torchaudio {torchaudio.__version__}, backends={backends}")
            if variant == "cuda":
                cuda = torch.cuda.is_available()
                gpu = torch.cuda.get_device_name(0) if cuda else "PyTorch does not see any GPU"
                report("CUDA available", cuda, f"CUDA {torch.version.cuda}, {gpu}")
            else:
                report("device", True, "CPU (no CUDA variant): synthesis will be slow", )
        except Exception as e:  # noqa: BLE001
            report("torch", False, repr(e))
    for pkg in ("f5-tts", "coqui-tts", "transformers"):
        report(f"{pkg} installed", local_pkgs[pkg] is not None, local_pkgs[pkg] or "not installed")
    try:
        from f5_tts.api import F5TTS  # noqa: F401

        report("F5-TTS imports", True)
    except Exception as e:  # noqa: BLE001
        report("F5-TTS imports", False, repr(e))
    try:
        from TTS.api import TTS  # noqa: F401

        report("XTTS (coqui-tts) imports", True)
    except Exception as e:  # noqa: BLE001
        report("XTTS (coqui-tts) imports", False, repr(e))
else:
    section("Local engines")
    print("`local` extra not installed: dummy engine only. For F5/XTTS: bats\\install.bat")
    if torch_v is not None:
        report("torch without engines", True, f"torch {torch_v} installed but without the local extra", warn_only=True)

# --------------------------------------------------------------------------- desktop app
section("Desktop app (desktop extra)")
pywebview_v = version("pywebview")
if pywebview_v is None:
    report("pywebview", False, "not installed: bats\\run.bat will open the browser "
           "(for the native window: bats\\update.bat or uv sync --extra desktop)", warn_only=True)
else:
    report("pywebview", True, pywebview_v)
    if sys.platform == "win32":
        import winreg

        webview2 = None
        for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE"),
                          (winreg.HKEY_CURRENT_USER, r"SOFTWARE")):
            try:
                key = sub + r"\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
                with winreg.OpenKey(hive, key) as k:
                    webview2 = winreg.QueryValueEx(k, "pv")[0]
                    break
            except OSError:
                continue
        report("Microsoft Edge WebView2 Runtime", bool(webview2) and webview2 != "0.0.0.0",
               webview2 or "not found: the app will use the browser "
               "(https://developer.microsoft.com/microsoft-edge/webview2/)", warn_only=True)

# --------------------------------------------------------------------------- models (informational)
if has_local:
    section("Models (informational)")
    try:
        from podcast_tts.models import MODELS, model_status

        for m in MODELS:
            st = model_status(m)
            state = "downloaded" if st["downloaded"] else "not downloaded (fetched on first use)"
            print(f"  {m.name:<11} {state}")
    except Exception as e:  # noqa: BLE001
        report("model status", False, repr(e), warn_only=True)

print("\nALL OK" if ok else "\nTHERE ARE ERRORS")
sys.exit(0 if ok else 1)
