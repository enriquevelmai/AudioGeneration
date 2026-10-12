"""Smoke test de F5-TTS: sintetiza una frase en castellano y otra en ingles.

Uso:  .venv\Scripts\python.exe scripts\smoke_f5.py
Salida: output/smoke_f5_es.wav, output/smoke_f5_en.wav (24 kHz mono)
"""
from __future__ import annotations

import time
from importlib.resources import files
from pathlib import Path

import torch
from f5_tts.api import F5TTS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

REF_WAV = str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav"))
REF_TEXT = "Some call me nature, others call me mother nature."

SENTENCES = {
    "es": "Hola, bienvenidos a este podcast generado localmente con inteligencia artificial.",
    "en": "Hello, and welcome to this podcast generated locally with artificial intelligence.",
}


def main() -> None:
    print("CUDA:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    t0 = time.perf_counter()
    tts = F5TTS(model="F5TTS_v1_Base", device="cuda" if torch.cuda.is_available() else "cpu")
    print(f"Carga del modelo: {time.perf_counter() - t0:.1f}s  (sample rate {tts.target_sample_rate} Hz)")

    for lang, text in SENTENCES.items():
        out = OUT / f"smoke_f5_{lang}.wav"
        t0 = time.perf_counter()
        wav, sr, _spec = tts.infer(
            ref_file=REF_WAV,
            ref_text=REF_TEXT,
            gen_text=text,
            nfe_step=32,
            speed=1.0,
            seed=42,
            file_wave=str(out),
            show_info=lambda *a, **k: None,
        )
        dt = time.perf_counter() - t0
        dur = len(wav) / sr
        print(f"[{lang}] {out.name}: {dur:.2f}s de audio en {dt:.2f}s (RTF {dt / dur:.3f}), sr={sr}")


if __name__ == "__main__":
    main()
