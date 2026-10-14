"""Shared pytest configuration."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Tests assert English texts: never pick up the developer's saved language (.env) or shell.
os.environ["PODCAST_TTS_LANG"] = "en"

requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")


@pytest.fixture(autouse=True)
def _english_ui(monkeypatch: pytest.MonkeyPatch):
    """Every test starts in English with a fresh language cache."""
    from podcast_tts import i18n

    monkeypatch.setenv("PODCAST_TTS_LANG", "en")
    i18n.reset_language()
    yield
    i18n.reset_language()


def write_tone(path: Path, seconds: float, sr: int = 44100, freq: float = 220.0,
               channels: int = 2) -> Path:
    """Write a 16-bit WAV with a tone (for tests)."""
    from pydub import AudioSegment

    t = np.arange(int(seconds * sr)) / sr
    x = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    if channels == 2:
        x = np.repeat(x, 2)
    seg = AudioSegment(x.tobytes(), frame_rate=sr, sample_width=2, channels=channels)
    path.parent.mkdir(parents=True, exist_ok=True)
    seg.export(str(path), format="wav")
    return path


@pytest.fixture
def tone_factory(tmp_path: Path):
    def make(name: str, seconds: float, **kw) -> Path:
        return write_tone(tmp_path / name, seconds, **kw)

    return make
