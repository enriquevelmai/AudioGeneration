"""Tests del ensamblador con el motor dummy (requiere ffmpeg para MP3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import SRC, requires_ffmpeg
from podcast_tts.assembler import (
    AssembleError,
    AssembleOptions,
    assemble,
    export_audio,
    generate,
    normalize_loudness,
    render,
)
from podcast_tts.engines import EngineError, get_engine
from podcast_tts.engines.base import TTSEngine
from podcast_tts.engines.dummy import DummyEngine
from podcast_tts.script_parser import Pause, Speech, parse_script
from podcast_tts.voices import add_voice


class CountingResolver:
    """Resolver que siempre devuelve un DummyEngine y cuenta llamadas."""

    def __init__(self) -> None:
        self.engine = DummyEngine()
        self.requested: list[str] = []

    def __call__(self, name: str) -> TTSEngine:
        self.requested.append(name)
        return self.engine


def opts(tmp_path: Path, **kw) -> AssembleOptions:
    kw.setdefault("cache_dir", tmp_path / "cache")
    kw.setdefault("engine_override", "dummy")
    kw.setdefault("base_dir", tmp_path)
    return AssembleOptions(**kw)


def test_dummy_engine_protocol() -> None:
    engine = get_engine("dummy")
    assert isinstance(engine, TTSEngine)
    assert get_engine("dummy") is engine
    from podcast_tts.voices import Voice

    a = engine.synthesize("Hola mundo", Voice("x", Path(".")), "es", 1.0)
    b = engine.synthesize("Hola mundo", Voice("x", Path(".")), "es", 2.0)
    assert a.dtype == np.float32 and a.ndim == 1
    assert a.size == pytest.approx(2 * b.size, rel=0.01)
    with pytest.raises(EngineError):
        get_engine("nope")


def test_stub_engines_raise_not_implemented(tmp_path) -> None:
    from podcast_tts.voices import Voice

    for name in ("f5", "xtts"):
        eng = get_engine(name)
        assert eng.sample_rate == 24000
        with pytest.raises(NotImplementedError):
            eng.synthesize("hola", Voice("x", tmp_path), "es")


def test_render_timeline_and_pauses(tmp_path) -> None:
    script = parse_script("[voz:ana] Hola qué tal.\n[pausa:2]\n[voz:carlos] Bien.")
    audio, sr = render(script, voices_dir=tmp_path, options=opts(tmp_path, target_lufs=None),
                       engine_resolver=CountingResolver())
    dummy = DummyEngine()
    expected = (max(0.3, len("Hola qué tal.") * dummy.seconds_per_char)
                + 2.0 + max(0.3, len("Bien.") * dummy.seconds_per_char))
    assert sr == 44100
    assert audio.size / sr == pytest.approx(expected, abs=0.02)
    # La pausa es silencio.
    start = int((len("Hola qué tal.") * 0.06 + 0.2) * sr)
    assert np.max(np.abs(audio[start:start + sr])) == 0.0


def test_cache_avoids_resynthesis(tmp_path) -> None:
    script = parse_script("[voz:ana] Una frase. [voz:carlos] Otra frase.")
    resolver = CountingResolver()
    options = opts(tmp_path)
    render(script, voices_dir=tmp_path, options=options, engine_resolver=resolver)
    assert resolver.engine.calls == 2
    render(script, voices_dir=tmp_path, options=options, engine_resolver=resolver)
    assert resolver.engine.calls == 2  # todo desde caché
    assert len(list((tmp_path / "cache").glob("*.npz"))) == 2
    render(parse_script("[voz:ana speed=1.2] Una frase."), voices_dir=tmp_path,
           options=options, engine_resolver=resolver)
    assert resolver.engine.calls == 3  # cambia speed -> nueva síntesis


def test_progress_callback(tmp_path) -> None:
    script = parse_script("[voz:ana] Uno. [pausa:0.5] [voz:ana] Dos.")
    calls: list[tuple[int, int, str]] = []
    render(script, voices_dir=tmp_path, options=opts(tmp_path),
           progress=lambda i, n, m: calls.append((i, n, m)))
    assert [c[0] for c in calls[:3]] == [1, 2, 3]
    assert all(c[1] == 3 for c in calls)
    assert "Mezclando" in calls[-1][2]


def test_missing_voice_errors_for_real_engines(tmp_path) -> None:
    script = parse_script("\n[voz:fantasma] Hola.")
    with pytest.raises(AssembleError, match="línea 2.*fantasma"):
        render(script, voices_dir=tmp_path,
               options=AssembleOptions(cache_dir=None, default_engine="f5"))


def test_missing_music_file(tmp_path) -> None:
    script = parse_script("[voz:ana] Hola.\n[musica:no_existe.mp3]")
    with pytest.raises(AssembleError, match="línea 2"):
        render(script, voices_dir=tmp_path, options=opts(tmp_path))


def test_engine_priority_and_voice_settings(tmp_path, tone_factory) -> None:
    pytest.importorskip("pydub")
    add_voice("ana", None, lang="en", engine="xtts", xtts_speaker="spk", speed=1.3,
              voices_dir=tmp_path / "voices")
    resolver = CountingResolver()
    script = parse_script("[voz:ana] Hola.")
    seen: list[tuple[str, float]] = []
    orig = resolver.engine.synthesize

    def spy(text, voice, lang, speed=1.0):
        seen.append((lang, speed))
        return orig(text, voice, lang, speed)

    resolver.engine.synthesize = spy  # type: ignore[method-assign]
    render(script, voices_dir=tmp_path / "voices", engine_resolver=resolver,
           options=AssembleOptions(cache_dir=None))
    assert resolver.requested == ["xtts"]  # motor del voice.json
    assert seen == [("en", 1.3)]


@requires_ffmpeg
def test_full_episode_mp3_with_music_and_sfx(tmp_path, tone_factory) -> None:
    from pydub import AudioSegment

    voices_dir = tmp_path / "voices"
    add_voice("ana", tone_factory("ana.wav", 6.0, freq=200), "Hola, soy Ana.",
              voices_dir=voices_dir)
    add_voice("carlos", tone_factory("carlos.wav", 6.0, freq=120), "Hola, soy Carlos.",
              lang="en", voices_dir=voices_dir)
    tone_factory("bed.wav", 3.0, freq=440)  # se repite en bucle
    tone_factory("ding.wav", 0.5, freq=880)
    tone_factory("intro.wav", 1.5, freq=330)

    script_path = tmp_path / "guion.md"
    script_path.write_text(
        """---
title: Test
lang: es
---
[musica:intro.wav vol=0.5 fade=0.3]
[musica:bed.wav fondo vol=0.1 fade=1]
[voz:ana] Bienvenidos al episodio de prueba. Hoy hablamos de muchas cosas.

[sfx:ding.wav vol=0.6]
[voz:carlos lang=en] Thanks Ana, glad to be here.
[pausa:2]
[voz:ana] Y esto es todo.
[musica:stop fade=1]
""",
        encoding="utf-8",
    )
    out = generate(script_path, tmp_path / "out" / "episodio.mp3", voices_dir=voices_dir,
                   options=AssembleOptions(engine_override="dummy", cache_dir=tmp_path / "c"))
    assert out.is_file() and out.stat().st_size > 10_000
    decoded = AudioSegment.from_file(str(out))
    assert 9.0 < decoded.duration_seconds < 14.0
    samples = np.array(decoded.get_array_of_samples(), dtype=np.float32) / 32768.0
    peak_db = 20 * np.log10(np.max(np.abs(samples)))
    assert peak_db <= 0.0  # sin saturar
    assert np.sqrt(np.mean(samples**2)) > 0.02  # hay señal

    wav = export_audio(assemble(parse_script("[voz:ana] Hola."), voices_dir=voices_dir,
                                options=opts(tmp_path)), tmp_path / "x.wav")
    assert AudioSegment.from_file(str(wav)).frame_rate == 44100


def test_background_ducking(tmp_path, tone_factory) -> None:
    tone_factory("bed.wav", 1.0, freq=440, channels=1)
    script = parse_script(
        "[musica:bed.wav fondo vol=0.1 fade=0]\n[pausa:3]\n[voz:ana] " + "texto " * 10 + "\n[pausa:3]"
    )
    audio, sr = render(script, voices_dir=tmp_path,
                       options=opts(tmp_path, target_lufs=None, duck_ramp=0.1))
    seg_pre = audio[int(1.0 * sr): int(2.0 * sr)]  # solo música, volumen alto
    rms_pre = np.sqrt(np.mean(seg_pre**2))
    assert rms_pre == pytest.approx(0.3 / np.sqrt(2) * 0.25, rel=0.1)  # 0.1 * 2.5
    assert audio.size / sr > 9.0  # música hasta el final


def test_normalize_loudness_targets_level() -> None:
    sr = 44100
    t = np.arange(sr * 3) / sr
    x = (0.01 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    y = normalize_loudness(x, sr, -16.0, -1.0)
    assert np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6
    assert np.max(np.abs(y)) > 0.1


def test_segments_list_input(tmp_path) -> None:
    audio, sr = render([Speech(voice="a", text="Hola."), Pause(seconds=1.0)],
                       voices_dir=tmp_path, options=opts(tmp_path, target_lufs=None))
    assert audio.size / sr == pytest.approx(1.3, abs=0.01)


@requires_ffmpeg
def test_cli_generate_parse_and_voices(tmp_path, tone_factory) -> None:
    script = tmp_path / "g.md"
    script.write_text("[voz:ana] Hola desde la CLI.\n[pausa:0.5]\n[voz:carlos] Adiós.", encoding="utf-8")
    env = {"PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8"}
    import os

    env = {**os.environ, **env}
    run = lambda *a: subprocess.run([sys.executable, "-m", "podcast_tts", *a], env=env,
                                    capture_output=True, text=True, encoding="utf-8")
    r = run("parse", str(script))
    assert r.returncode == 0, r.stderr
    assert '"voice": "ana"' in r.stdout

    out = tmp_path / "ep.mp3"
    r = run("generate", str(script), "-o", str(out), "--engine", "dummy",
            "--voices-dir", str(tmp_path / "v"), "--cache-dir", str(tmp_path / "c"))
    assert r.returncode == 0, r.stderr
    assert out.is_file() and "Listo" in r.stderr

    wav = tone_factory("clip.wav", 5.0)
    vd = str(tmp_path / "v")
    assert run("voices", "add", "ana", str(wav), "--text", "Hola.", "--voices-dir", vd).returncode == 0
    r = run("voices", "list", "--voices-dir", vd)
    assert "ana" in r.stdout
    assert run("voices", "remove", "ana", "--voices-dir", vd).returncode == 0
    r = run("voices", "remove", "ana", "--voices-dir", vd)
    assert r.returncode == 1 and "no existe" in r.stderr

    bad = tmp_path / "bad.md"
    bad.write_text("[voz:ana] hola\n[raro:1]", encoding="utf-8")
    r = run("parse", str(bad))
    assert r.returncode == 1 and "Línea 2" in r.stderr
