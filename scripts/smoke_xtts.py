"""Smoke test de XTTS v2 (coqui-tts, fork idiap): castellano e ingles con un speaker integrado.

Uso:  .venv\Scripts\python.exe scripts\smoke_xtts.py
Salida: output/smoke_xtts_es.wav, output/smoke_xtts_en.wav (24 kHz mono)
La primera ejecucion descarga ~1.9 GB a %LOCALAPPDATA%\tts\tts_models--multilingual--multi-dataset--xtts_v2
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")  # acepta la licencia CPML sin prompt interactivo

import torch  # noqa: E402
from TTS.api import TTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
SPEAKER = "Ana Florence"
SENTENCES = {
    "es": "Hola, bienvenidos a este podcast generado localmente con inteligencia artificial.",
    "en": "Hello, and welcome to this podcast generated locally with artificial intelligence.",
}


def main() -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if device == "cuda" else "")
    t0 = time.perf_counter()
    tts = TTS(MODEL, progress_bar=False).to(device)
    print(f"Carga del modelo: {time.perf_counter() - t0:.1f}s")
    sr = tts.synthesizer.output_sample_rate
    print("Sample rate:", sr)
    print("Idiomas:", tts.languages)
    speakers = tts.speakers or []
    print(f"Speakers integrados ({len(speakers)}):")
    for s in speakers:
        print("  -", s)

    for lang, text in SENTENCES.items():
        out = OUT / f"smoke_xtts_{lang}.wav"
        t0 = time.perf_counter()
        tts.tts_to_file(text=text, speaker=SPEAKER, language=lang, file_path=str(out))
        dt = time.perf_counter() - t0
        import soundfile as sf

        info = sf.info(str(out))
        print(f"[{lang}] {out.name}: {info.duration:.2f}s de audio en {dt:.2f}s (RTF {dt / info.duration:.3f}), sr={info.samplerate}")


if __name__ == "__main__":
    main()
