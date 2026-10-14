"""Tests for the voice registry."""

from __future__ import annotations

import json
import wave

import pytest

from conftest import requires_ffmpeg
from podcast_tts.voices import (
    VoiceError,
    VoiceNotFoundError,
    add_voice,
    get_voice,
    list_voices,
    remove_voice,
)


@requires_ffmpeg
def test_add_get_list_remove(tmp_path, tone_factory) -> None:
    src = tone_factory("largo.wav", 20.0, sr=44100, channels=2)
    voices_dir = tmp_path / "voices"
    with pytest.warns(UserWarning, match="trimmed"):
        voice = add_voice("ana", src, "Hola, soy Ana.", lang="es", engine="f5",
                          description="Voz de prueba", speed=1.05, voices_dir=voices_dir)

    assert voice.ref_wav.is_file()
    with wave.open(str(voice.ref_wav)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 24000
        assert w.getsampwidth() == 2
        assert w.getnframes() / w.getframerate() == pytest.approx(15.0, abs=0.05)

    cfg = json.loads((voices_dir / "ana" / "voice.json").read_text(encoding="utf-8"))
    assert cfg == {"name": "ana", "lang": "es", "engine": "f5", "description": "Voz de prueba",
                   "xtts_speaker": None, "speed": 1.05}
    assert voice.ref_text == "Hola, soy Ana."

    loaded = get_voice("ana", voices_dir)
    assert loaded.speed == 1.05 and loaded.engine == "f5" and loaded.has_ref
    assert [v.name for v in list_voices(voices_dir)] == ["ana"]

    with pytest.raises(VoiceError, match="already exists"):
        add_voice("ana", src, "x", voices_dir=voices_dir)

    remove_voice("ana", voices_dir)
    assert list_voices(voices_dir) == []
    with pytest.raises(VoiceNotFoundError):
        get_voice("ana", voices_dir)


@requires_ffmpeg
def test_short_clip_warns_and_overwrite(tmp_path, tone_factory) -> None:
    voices_dir = tmp_path / "voices"
    add_voice("carlos", tone_factory("a.wav", 6.0, channels=1), "Hola.", lang="es",
              voices_dir=voices_dir)
    with pytest.warns(UserWarning, match="only"):
        v = add_voice("carlos", tone_factory("b.wav", 1.0), "Hi.", lang="en", engine="xtts",
                      voices_dir=voices_dir, overwrite=True)
    assert get_voice("carlos", voices_dir).lang == "en"
    assert v.engine == "xtts"


def test_xtts_speaker_without_wav(tmp_path) -> None:
    v = add_voice("narrador", None, lang="en", engine="xtts", xtts_speaker="Claribel Dervla",
                  voices_dir=tmp_path)
    assert not v.has_ref
    assert get_voice("narrador", tmp_path).xtts_speaker == "Claribel Dervla"


def test_invalid_inputs(tmp_path) -> None:
    with pytest.raises(VoiceError, match="invalid"):
        add_voice("con espacio", None, xtts_speaker="x", voices_dir=tmp_path)
    with pytest.raises(VoiceError, match="engine"):
        add_voice("ok", None, xtts_speaker="x", engine="otro", voices_dir=tmp_path)
    with pytest.raises(VoiceError, match="reference"):
        add_voice("ok", None, voices_dir=tmp_path)
    with pytest.raises(VoiceError, match="does not exist"):
        add_voice("ok", tmp_path / "nada.wav", "x", voices_dir=tmp_path)
    assert list_voices(tmp_path / "no_existe") == []


# --------------------------------------------------------------------------- #
# Regressions from the code review
# --------------------------------------------------------------------------- #


def _make_voice_dir(root, name: str, content: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "voice.json").write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        "{no es json",
        '["una", "lista"]',
        '"texto"',
        '{"speed": "rapido"}',
        '{"speed": [1]}',
        '{"speed": "nan"}',
        '{"provider_options": [1, 2]}',
        '{"xtts_speaker": 3}',
    ],
)
def test_broken_voice_json_is_voice_error_and_skipped(tmp_path, content: str) -> None:
    _make_voice_dir(tmp_path, "rota", content)
    _make_voice_dir(tmp_path, "buena", '{"engine": "xtts", "xtts_speaker": "Ana Florence"}')
    with pytest.raises(VoiceError):
        get_voice("rota", voices_dir=tmp_path)
    with pytest.warns(UserWarning, match="rota"):
        voices = list_voices(tmp_path)
    assert [v.name for v in voices] == ["buena"]


@pytest.mark.parametrize("name", ["../secreto", "..", "a/../../b", "..\\secreto", "/abs", "C:\\x"])
def test_get_voice_rejects_path_traversal(tmp_path, name: str) -> None:
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    _make_voice_dir(tmp_path, "secreto", '{"engine": "xtts", "xtts_speaker": "Ana Florence"}')
    with pytest.raises(VoiceNotFoundError):
        get_voice(name, voices_dir=voices_dir)


@pytest.mark.parametrize("name", ["CON", "con", "Prn", "aux", "NUL", "COM1", "com9", "LPT1", "lpt9"])
def test_reserved_windows_names_rejected(tmp_path, name: str) -> None:
    with pytest.raises(VoiceError, match="reserved"):
        add_voice(name, None, xtts_speaker="Ana Florence", engine="xtts", voices_dir=tmp_path)
    with pytest.raises(VoiceError):
        remove_voice(name, voices_dir=tmp_path)


def test_names_similar_to_reserved_are_allowed(tmp_path) -> None:
    for name in ("console", "COM10", "nul_2", "LPT0"):
        add_voice(name, None, xtts_speaker="Ana Florence", engine="xtts", voices_dir=tmp_path)
    assert {v.name for v in list_voices(tmp_path)} == {"console", "COM10", "nul_2", "LPT0"}
