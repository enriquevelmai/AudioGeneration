"""Assembler tests with the dummy engine (MP3 requires ffmpeg)."""

from __future__ import annotations

import re
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
    """Resolver that always returns a DummyEngine and counts calls."""

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

    a = engine.synthesize("Hello world", Voice("x", Path(".")), "es", 1.0)
    b = engine.synthesize("Hello world", Voice("x", Path(".")), "es", 2.0)
    assert a.dtype == np.float32 and a.ndim == 1
    assert a.size == pytest.approx(2 * b.size, rel=0.01)
    with pytest.raises(EngineError):
        get_engine("nope")


def test_real_engines_lazy_and_validate_without_loading(tmp_path) -> None:
    """f5/xtts are instantiated without loading models and validate language/voice before loading them."""
    from podcast_tts.engines import EngineError, engine_info
    from podcast_tts.engines import f5 as f5_mod
    from podcast_tts.engines import xtts as xtts_mod
    from podcast_tts.voices import Voice

    f5_loaded, xtts_loaded = f5_mod.loaded_models(), xtts_mod.is_loaded()
    for name in ("f5", "xtts"):
        eng = get_engine(name)
        assert eng.name == name
        assert eng.sample_rate == 24000
    voice = Voice("x", tmp_path)  # no ref.wav and no xtts_speaker
    with pytest.raises(EngineError, match="xtts"):
        get_engine("f5").synthesize("bonjour", voice, "fr")
    with pytest.raises(EngineError, match="reference"):
        get_engine("f5").synthesize("hola", voice, "es")
    with pytest.raises(EngineError, match="language"):
        get_engine("xtts").synthesize("hola", voice, "xx")
    with pytest.raises(EngineError):
        get_engine("xtts").synthesize("hola", voice, "es")
    assert xtts_mod.normalize_lang("zh") == "zh-cn"
    # None of the above should have loaded any model.
    assert f5_mod.loaded_models() == f5_loaded
    assert xtts_mod.is_loaded() == xtts_loaded
    info = engine_info()
    assert set(info) >= {"f5", "xtts", "dummy"}
    assert all({"importable", "cuda", "loaded"} <= set(v) for v in info.values())


def test_render_timeline_and_pauses(tmp_path) -> None:
    script = parse_script("[voice:ana] Hello, how are you.\n[pause:2]\n[voice:carlos] Fine.")
    audio, sr = render(script, voices_dir=tmp_path, options=opts(tmp_path, target_lufs=None),
                       engine_resolver=CountingResolver())
    dummy = DummyEngine()
    expected = (max(0.3, len("Hello, how are you.") * dummy.seconds_per_char)
                + 2.0 + max(0.3, len("Fine.") * dummy.seconds_per_char))
    assert sr == 44100
    assert audio.size / sr == pytest.approx(expected, abs=0.02)
    # The pause is silence.
    start = int((len("Hello, how are you.") * 0.06 + 0.2) * sr)
    assert np.max(np.abs(audio[start:start + sr])) == 0.0


def test_cache_avoids_resynthesis(tmp_path) -> None:
    script = parse_script("[voice:ana] One sentence. [voice:carlos] Another sentence.")
    resolver = CountingResolver()
    options = opts(tmp_path)
    render(script, voices_dir=tmp_path, options=options, engine_resolver=resolver)
    assert resolver.engine.calls == 2
    render(script, voices_dir=tmp_path, options=options, engine_resolver=resolver)
    assert resolver.engine.calls == 2  # everything from the cache
    assert len(list((tmp_path / "cache").glob("*.npz"))) == 2
    render(parse_script("[voice:ana speed=1.2] One sentence."), voices_dir=tmp_path,
           options=options, engine_resolver=resolver)
    assert resolver.engine.calls == 3  # speed changes -> new synthesis


def test_progress_callback(tmp_path) -> None:
    script = parse_script("[voice:ana] One. [pause:0.5] [voice:ana] Two.")
    calls: list[tuple[int, int, str]] = []
    render(script, voices_dir=tmp_path, options=opts(tmp_path),
           progress=lambda i, n, m: calls.append((i, n, m)))
    assert [c[0] for c in calls[:3]] == [1, 2, 3]
    assert all(c[1] == 3 for c in calls)
    assert "Mixing" in calls[-1][2]
    assert calls[0][2].startswith("Synthesizing [ana]")


def test_missing_voice_errors_for_real_engines(tmp_path) -> None:
    script = parse_script("\n[voice:ghost] Hello.")
    with pytest.raises(AssembleError, match="line 2.*ghost"):
        render(script, voices_dir=tmp_path,
               options=AssembleOptions(cache_dir=None, default_engine="f5"))


def test_missing_music_file(tmp_path) -> None:
    script = parse_script("[voice:ana] Hello.\n[music:missing.mp3]")
    with pytest.raises(AssembleError, match="line 2"):
        render(script, voices_dir=tmp_path, options=opts(tmp_path))


def test_engine_priority_and_voice_settings(tmp_path, tone_factory) -> None:
    pytest.importorskip("pydub")
    add_voice("ana", None, lang="en", engine="xtts", xtts_speaker="spk", speed=1.3,
              voices_dir=tmp_path / "voices")
    resolver = CountingResolver()
    script = parse_script("[voice:ana] Hello.")
    seen: list[tuple[str, float]] = []
    orig = resolver.engine.synthesize

    def spy(text, voice, lang, speed=1.0):
        seen.append((lang, speed))
        return orig(text, voice, lang, speed)

    resolver.engine.synthesize = spy  # type: ignore[method-assign]
    render(script, voices_dir=tmp_path / "voices", engine_resolver=resolver,
           options=AssembleOptions(cache_dir=None))
    assert resolver.requested == ["xtts"]  # engine from voice.json
    assert seen == [("en", 1.3)]


@requires_ffmpeg
def test_full_episode_mp3_with_music_and_sfx(tmp_path, tone_factory) -> None:
    from pydub import AudioSegment

    voices_dir = tmp_path / "voices"
    add_voice("ana", tone_factory("ana.wav", 6.0, freq=200), "Hi, I am Ana.",
              voices_dir=voices_dir)
    add_voice("carlos", tone_factory("carlos.wav", 6.0, freq=120), "Hi, I am Carlos.",
              lang="en", voices_dir=voices_dir)
    tone_factory("bed.wav", 3.0, freq=440)  # loops
    tone_factory("ding.wav", 0.5, freq=880)
    tone_factory("intro.wav", 1.5, freq=330)

    script_path = tmp_path / "script.md"
    script_path.write_text(
        """---
title: Test
lang: es
---
[music:intro.wav vol=0.5 fade=0.3]
[music:bed.wav bg vol=0.1 fade=1]
[voice:ana] Bienvenidos al episodio de prueba. Hoy hablamos de muchas cosas.

[sfx:ding.wav vol=0.6]
[voice:carlos lang=en] Thanks Ana, glad to be here.
[pause:2]
[voice:ana] Y esto es todo.
[music:stop fade=1]
""",
        encoding="utf-8",
    )
    out = generate(script_path, tmp_path / "out" / "episode.mp3", voices_dir=voices_dir,
                   options=AssembleOptions(engine_override="dummy", cache_dir=tmp_path / "c"))
    assert out.is_file() and out.stat().st_size > 10_000
    decoded = AudioSegment.from_file(str(out))
    assert 9.0 < decoded.duration_seconds < 14.0
    samples = np.array(decoded.get_array_of_samples(), dtype=np.float32) / 32768.0
    peak_db = 20 * np.log10(np.max(np.abs(samples)))
    assert peak_db <= 0.0  # no clipping
    assert np.sqrt(np.mean(samples**2)) > 0.02  # there is signal

    wav = export_audio(assemble(parse_script("[voice:ana] Hello."), voices_dir=voices_dir,
                                options=opts(tmp_path)), tmp_path / "x.wav")
    assert AudioSegment.from_file(str(wav)).frame_rate == 44100


def test_background_ducking(tmp_path, tone_factory) -> None:
    tone_factory("bed.wav", 1.0, freq=440, channels=1)
    script = parse_script(
        "[music:bed.wav bg vol=0.1 fade=0]\n[pause:3]\n[voice:ana] " + "words " * 10 + "\n[pause:3]"
    )
    audio, sr = render(script, voices_dir=tmp_path,
                       options=opts(tmp_path, target_lufs=None, duck_ramp=0.1))
    seg_pre = audio[int(1.0 * sr): int(2.0 * sr)]  # music only, high volume
    rms_pre = np.sqrt(np.mean(seg_pre**2))
    assert rms_pre == pytest.approx(0.3 / np.sqrt(2) * 0.25, rel=0.1)  # 0.1 * 2.5
    assert audio.size / sr > 9.0  # music until the end


def test_normalize_loudness_targets_level() -> None:
    sr = 44100
    t = np.arange(sr * 3) / sr
    x = (0.01 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    y = normalize_loudness(x, sr, -16.0, -1.0)
    assert np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6
    assert np.max(np.abs(y)) > 0.1


def test_noisy_third_party_warnings_are_filtered() -> None:
    import warnings

    from podcast_tts._warnings import silence_noisy_warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        silence_noisy_warnings()
        warnings.warn("In 2.9, this function's implementation will be changed to use x")
        warnings.warn("'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'X' instead.",
                      DeprecationWarning)
        warnings.warn("this warning is shown")
    assert [str(w.message) for w in caught] == ["this warning is shown"]


def test_normalize_loudness_hits_target_with_peaky_audio() -> None:
    """Regression: the peak limiter left episodes ~1.5 LU below -16 LUFS."""
    pyloudnorm = pytest.importorskip("pyloudnorm")
    sr = 44100
    rng = np.random.default_rng(0)
    t = np.arange(sr * 8) / sr
    # "Speech" with syllables and sporadic peaks (high crest factor, like real speech)
    x = 0.05 * np.sin(2 * np.pi * 180 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t) ** 2)
    x += 0.01 * rng.standard_normal(t.size)
    spikes = rng.choice(t.size, 40, replace=False)
    x[spikes] = 0.9 * np.sign(rng.standard_normal(40))
    x = x.astype(np.float32)
    for target in (-16.0, -14.0, -20.0):
        y = normalize_loudness(x, sr, target, -1.0)
        assert np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6
        measured = pyloudnorm.Meter(sr).integrated_loudness(y.astype(np.float64))
        assert measured == pytest.approx(target, abs=0.5)


def test_segments_list_input(tmp_path) -> None:
    audio, sr = render([Speech(voice="a", text="Hey."), Pause(seconds=1.0)],
                       voices_dir=tmp_path, options=opts(tmp_path, target_lufs=None))
    assert audio.size / sr == pytest.approx(1.3, abs=0.01)


@requires_ffmpeg
def test_cli_generate_parse_and_voices(tmp_path, tone_factory) -> None:
    script = tmp_path / "g.md"
    script.write_text("[voice:ana] Hello from the CLI.\n[pause:0.5]\n[voice:carlos] Bye.", encoding="utf-8")
    env = {"PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8", "PODCAST_TTS_LANG": "en"}
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
    assert out.is_file() and "Done" in r.stderr
    # Regression: audio duration and generation time are reported separately
    assert re.search(r"duration \d+\.\d s, generated in \d+\.\d s", r.stderr), r.stderr

    wav = tone_factory("clip.wav", 5.0)
    vd = str(tmp_path / "v")
    assert run("voices", "add", "ana", str(wav), "--text", "Hello.", "--voices-dir", vd).returncode == 0
    r = run("voices", "list", "--voices-dir", vd)
    assert "ana" in r.stdout
    assert run("voices", "remove", "ana", "--voices-dir", vd).returncode == 0
    r = run("voices", "remove", "ana", "--voices-dir", vd)
    assert r.returncode == 1 and "does not exist" in r.stderr

    bad = tmp_path / "bad.md"
    bad.write_text("[voice:ana] hello\n[weird:1]", encoding="utf-8")
    r = run("parse", str(bad))
    assert r.returncode == 1 and "Line 2" in r.stderr


# --------------------------------------------------------------------------- #
# Regressions from the code review
# --------------------------------------------------------------------------- #


def test_render_overflow_is_assemble_error(tmp_path) -> None:
    # A non-finite pause (bypassing the parser) must not end in OverflowError.
    with pytest.raises(AssembleError, match="too long"):
        render([Pause(seconds=float("inf"))], voices_dir=tmp_path, options=opts(tmp_path))
    with pytest.raises(AssembleError, match="too long"):
        render([Pause(seconds=1e15)], voices_dir=tmp_path, options=opts(tmp_path))


def test_no_ffmpeg_gives_clear_error(tmp_path, tone_factory, monkeypatch) -> None:
    import podcast_tts.assembler as asm

    monkeypatch.setattr(asm.shutil, "which", lambda *_a, **_k: None)
    audio = assemble([Speech(voice="a", text="Hello.")], voices_dir=tmp_path,
                     options=opts(tmp_path))
    with pytest.raises(AssembleError, match="winget install Gyan.FFmpeg"):
        export_audio(audio, tmp_path / "out.mp3")
    # WAV does not need ffmpeg
    assert export_audio(audio, tmp_path / "out.wav").is_file()
    # Loading non-WAV audio does
    (tmp_path / "music.mp3").write_bytes(b"irrelevant")
    with pytest.raises(AssembleError, match="ffmpeg"):
        render(parse_script("[music:music.mp3]"), voices_dir=tmp_path, options=opts(tmp_path))
    tone_factory("bed.wav", 0.5, channels=1)
    audio, _sr = render(parse_script("[music:bed.wav]"), voices_dir=tmp_path,
                        options=opts(tmp_path))
    assert audio.size > 0


@pytest.mark.parametrize("raw", ["../outside.wav", "sub/../../outside.wav", "ABS", "C:outside.wav",
                                 "\\outside.wav"])
def test_external_paths_rejected_in_remote_mode(tmp_path, tone_factory, raw) -> None:
    base = tmp_path / "script"
    base.mkdir()
    outside = tone_factory("outside.wav", 0.5, channels=1)
    if raw == "ABS":
        raw = str(outside)
    script = parse_script(f'[sfx:"{raw}"]')
    with pytest.raises(AssembleError, match="not allowed"):
        render(script, voices_dir=tmp_path,
               options=opts(tmp_path, base_dir=base, allow_external_paths=False))


def test_relative_paths_allowed_in_remote_mode(tmp_path, tone_factory) -> None:
    base = tmp_path / "script"
    tone_factory("script/sfx/ok.wav", 0.5, channels=1)
    script = parse_script("[sfx:sfx/ok.wav]\n[pause:1]")
    audio, sr = render(script, voices_dir=tmp_path,
                       options=opts(tmp_path, base_dir=base, allow_external_paths=False))
    assert audio.size / sr == pytest.approx(1.0, abs=0.01)
    # A relative file missing from base_dir and the project is not looked up in the cwd
    with pytest.raises(AssembleError, match="does not exist"):
        render(parse_script("[sfx:nothing.wav]"), voices_dir=tmp_path,
               options=opts(tmp_path, base_dir=base, allow_external_paths=False))
    # In local mode absolute paths still work
    render(parse_script(f'[sfx:"{tmp_path / "script" / "sfx" / "ok.wav"}"]'),
           voices_dir=tmp_path, options=opts(tmp_path, base_dir=base))


class TaggedDummy(DummyEngine):
    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag

    @property
    def cache_tag(self) -> str:
        return self.tag


def test_cache_key_depends_on_engine_cache_tag(tmp_path) -> None:
    script = parse_script("[voice:ana] Hello.")
    options = opts(tmp_path)
    engine = TaggedDummy("model-v1")
    render(script, voices_dir=tmp_path, options=options, engine_resolver=lambda _n: engine)
    render(script, voices_dir=tmp_path, options=options, engine_resolver=lambda _n: engine)
    assert engine.calls == 1
    engine.tag = "model-v2"
    render(script, voices_dir=tmp_path, options=options, engine_resolver=lambda _n: engine)
    assert engine.calls == 2


def test_builtin_engines_declare_cache_tag() -> None:
    from podcast_tts.engines.azure import AzureEngine
    from podcast_tts.engines.base import engine_cache_tag
    from podcast_tts.engines.elevenlabs import ElevenLabsEngine
    from podcast_tts.engines.f5 import F5Engine
    from podcast_tts.engines.openai import OpenAIEngine
    from podcast_tts.engines.xtts import XTTSEngine

    f5_a, f5_b = engine_cache_tag(F5Engine()), engine_cache_tag(F5Engine(nfe_step=16))
    assert "F5-Spanish" in f5_a and "nfe=32" in f5_a and f5_a != f5_b
    xtts = engine_cache_tag(XTTSEngine())
    assert "xtts_v2" in xtts and "coqui-tts=" in xtts
    assert engine_cache_tag(XTTSEngine(temperature=0.5)) != xtts
    assert "eleven_" in engine_cache_tag(ElevenLabsEngine(api_key="x"))
    assert engine_cache_tag(OpenAIEngine(api_key="x", model="m1")) != engine_cache_tag(
        OpenAIEngine(api_key="x", model="m2"))
    assert engine_cache_tag(AzureEngine(api_key="x")).startswith("azure")
    assert engine_cache_tag(object()) == ""
