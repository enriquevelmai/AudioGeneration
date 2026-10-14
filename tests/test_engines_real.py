"""Tests with the real models (slow): `pytest -m slow`.

They use the sample voices in ``voices/`` (see scripts/make_sample_voices.py).
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from podcast_tts.engines import get_engine
from podcast_tts.voices import default_voices_dir, get_voice

pytestmark = pytest.mark.slow


def _voice(name: str):
    if not (default_voices_dir() / name / "voice.json").is_file():
        pytest.skip(f"sample voice '{name}' is missing (run scripts/make_sample_voices.py)")
    return get_voice(name)


@pytest.fixture(autouse=True)
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _check(audio: np.ndarray, sr: int) -> None:
    assert sr == 24000
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert audio.size / sr > 0.5
    assert np.isfinite(audio).all()
    assert float(np.abs(audio).max()) > 0.01  # not silence


@pytest.mark.parametrize(("voice", "lang", "text"), [
    ("ana", "es", "Hola, esto es una prueba del motor F5 en castellano."),
    ("emma", "en", "Hello, this is a quick test of the F5 engine."),
])
def test_f5_synthesizes(voice: str, lang: str, text: str) -> None:
    engine = get_engine("f5")
    _check(engine.synthesize(text, _voice(voice), lang, 1.0), engine.sample_rate)


@pytest.mark.parametrize(("voice", "lang", "text"), [
    ("david", "en", "Hello, this is a quick test of the XTTS engine."),  # built-in speaker
    ("carlos", "es", "Hola, esto es una prueba de clonación con XTTS."),  # cloning from ref.wav
])
def test_xtts_synthesizes(voice: str, lang: str, text: str) -> None:
    engine = get_engine("xtts")
    _check(engine.synthesize(text, _voice(voice), lang, 1.0), engine.sample_rate)
