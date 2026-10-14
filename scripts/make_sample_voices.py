"""Generates the sample voices in ``voices/`` using XTTS v2 built-in speakers.

For each voice it synthesizes with XTTS a ~8-11 s reference clip with a natural
sentence, registers it with ``add_voice`` (ref.wav + ref.txt with the exact
transcript + voice.json) and checks the duration (F5-TTS trims references to
~12 s, so they must not exceed ~11.5 s).

Usage:
    .venv\\Scripts\\python.exe scripts\\make_sample_voices.py              # creates the missing ones
    .venv\\Scripts\\python.exe scripts\\make_sample_voices.py --overwrite  # regenerates all of them
    .venv\\Scripts\\python.exe scripts\\make_sample_voices.py ana emma     # only those
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from podcast_tts.voices import Voice, add_voice, default_voices_dir  # noqa: E402

MIN_SECONDS = 6.0
MAX_SECONDS = 11.5


@dataclass(frozen=True)
class Sample:
    name: str
    lang: str
    engine: str
    speaker: str  # XTTS built-in speaker used to generate the clip
    text: str
    description: str
    keep_speaker: bool = False  # stores xtts_speaker in voice.json


SAMPLES: tuple[Sample, ...] = (
    Sample(
        "ana", "es", "f5", "Alma María",
        "Hola, me llamo Ana y me encanta contar historias. Cada mañana preparo un café, "
        "abro la ventana y pienso en lo que voy a compartir con vosotros.",
        "Woman, Spanish (Spain). Clip generated with the XTTS speaker 'Alma María'.",
    ),
    Sample(
        "carlos", "es", "f5", "Luis Moray",
        "Buenas tardes, soy Carlos. Llevo años trabajando en la radio y todavía me emociono "
        "cada vez que se enciende la luz roja del estudio.",
        "Man, Spanish (Spain). Clip generated with the XTTS speaker 'Luis Moray'.",
    ),
    Sample(
        "emma", "en", "f5", "Claribel Dervla",
        "Hi, I'm Emma. I love long walks by the sea, a good cup of tea, and stories that "
        "make you think about the world a little differently.",
        "Woman, English. Clip generated with the XTTS speaker 'Claribel Dervla'.",
    ),
    Sample(
        "david", "en", "xtts", "Damien Black",
        "Hello, my name is David. I have been reading the news on the radio for years, and "
        "I still believe that a calm voice makes every story easier to follow.",
        "Man, English. XTTS built-in speaker 'Damien Black' (ref.wav also usable with F5).",
        keep_speaker=True,
    ),
)


def synth_clip(tts, sample: Sample, out: Path, attempts: int = 4) -> float:
    """Synthesizes the clip with XTTS until the duration falls within [MIN, MAX]."""
    import torch

    sr = tts.synthesizer.output_sample_rate
    best: tuple[float, np.ndarray] | None = None
    for i in range(attempts):
        torch.manual_seed(1234 + i)
        with torch.inference_mode():
            wav = tts.tts(text=sample.text, speaker=sample.speaker, language=sample.lang,
                          temperature=0.6, split_sentences=True)
        audio = np.asarray(wav, dtype=np.float32)
        dur = len(audio) / sr
        print(f"  attempt {i + 1}: {dur:.2f} s")
        if best is None or abs(dur - 9.5) < abs(best[0] - 9.5):
            best = (dur, audio)
        if MIN_SECONDS <= dur <= MAX_SECONDS:
            break
    assert best is not None
    dur, audio = best
    if not MIN_SECONDS <= dur <= MAX_SECONDS:
        print(f"  WARNING: duration {dur:.2f} s outside [{MIN_SECONDS}, {MAX_SECONDS}]")
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio * min(1.0, 0.9 / peak)
    sf.write(str(out), audio, sr, subtype="PCM_16")
    return dur


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="voices to generate (default: all)")
    parser.add_argument("--overwrite", action="store_true", help="regenerates them even if they already exist")
    parser.add_argument("--voices-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    voices_dir = args.voices_dir or default_voices_dir()
    wanted = [s for s in SAMPLES if not args.names or s.name in args.names]
    todo = [s for s in wanted if args.overwrite or not (voices_dir / s.name / "voice.json").is_file()]
    if not todo:
        print("All sample voices already exist (use --overwrite to regenerate them).")
        return 0

    from podcast_tts.engines.xtts import _load_model

    t0 = time.perf_counter()
    tts = _load_model()
    print(f"XTTS loaded in {time.perf_counter() - t0:.1f} s")

    with tempfile.TemporaryDirectory() as tmp:
        for s in todo:
            print(f"[{s.name}] {s.lang} / {s.engine} / speaker '{s.speaker}'")
            raw = Path(tmp) / f"{s.name}.wav"
            dur = synth_clip(tts, s, raw)
            voice: Voice = add_voice(
                s.name, raw, transcript=s.text, lang=s.lang, engine=s.engine,
                description=s.description,
                xtts_speaker=s.speaker if s.keep_speaker else None,
                voices_dir=voices_dir, overwrite=True,
            )
            print(f"  -> {voice.path} ({dur:.2f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
