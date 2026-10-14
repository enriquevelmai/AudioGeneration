"""Engine registry: built-in engines, simulated entry points and runtime registration."""

from __future__ import annotations

import subprocess
import sys
import types
from importlib import metadata
from pathlib import Path

import numpy as np
import pytest

from podcast_tts import engines
from podcast_tts.engines import (
    EngineError,
    LicenseInfo,
    engine_info,
    engine_license,
    engine_names,
    get_engine,
    refresh_engines,
    register_engine,
    unregister_engine,
)
from podcast_tts.script_parser import ScriptParseError, parse_script

SRC = Path(__file__).resolve().parents[1] / "src"


class FakeEngine:
    """Minimal third-party engine (what podcast-tts-myengine would publish)."""

    name = "fake"
    kind = "cloud"
    required_config = ("FAKE_TTS_KEY",)
    license_info = LicenseInfo(name="MIT", url="https://example.invalid", commercial_use=True)

    def __init__(self, gain: float = 0.1) -> None:
        self.gain = gain

    @property
    def sample_rate(self) -> int:
        return 16000

    def synthesize(self, text, voice, lang, speed=1.0):
        return np.full(len(text), self.gain, dtype=np.float32)


@pytest.fixture
def fake_plugin(monkeypatch):
    """Simulate an installed package that declares entry points in ``podcast_tts.engines``."""
    module = types.ModuleType("podcast_tts_fakeplugin")
    module.FakeEngine = FakeEngine

    class NoLicense(FakeEngine):
        license_info = None  # type: ignore[assignment]
        kind = "local"
        required_config = ()

    module.NoLicense = NoLicense
    monkeypatch.setitem(sys.modules, "podcast_tts_fakeplugin", module)
    eps = [
        metadata.EntryPoint("fake", "podcast_tts_fakeplugin:FakeEngine", engines.ENTRY_POINT_GROUP),
        metadata.EntryPoint("nolicense", "podcast_tts_fakeplugin:NoLicense",
                            engines.ENTRY_POINT_GROUP),
        metadata.EntryPoint("broken", "podcast_tts_no_existe:Engine", engines.ENTRY_POINT_GROUP),
        metadata.EntryPoint("f5", "podcast_tts_fakeplugin:FakeEngine", engines.ENTRY_POINT_GROUP),
    ]

    def fake_entry_points(**kwargs):
        if kwargs.get("group") == engines.ENTRY_POINT_GROUP:
            return metadata.EntryPoints(eps)
        return metadata.EntryPoints([])

    monkeypatch.setattr(metadata, "entry_points", fake_entry_points)
    monkeypatch.delenv("FAKE_TTS_KEY", raising=False)
    refresh_engines()
    yield
    monkeypatch.undo()
    refresh_engines()


def test_builtin_names_and_dynamic_constants() -> None:
    names = engine_names()
    assert names[:6] == ("f5", "xtts", "dummy", "elevenlabs", "azure", "openai")
    assert engines.ENGINE_NAMES == names
    from podcast_tts import script_parser, voices

    assert script_parser.KNOWN_ENGINES == names
    assert voices.VOICE_ENGINES == names


def test_builtin_licenses() -> None:
    assert engine_license("f5").commercial_use is False
    assert "CC-BY-NC" in engine_license("f5").name
    assert engine_license("xtts").commercial_use is False
    assert engine_license("dummy").commercial_use is True
    for name in ("elevenlabs", "azure", "openai"):
        assert engine_license(name).commercial_use in (True, "depends on plan")
    from podcast_tts.engines.f5 import F5Engine
    from podcast_tts.engines.xtts import XTTSEngine

    assert isinstance(F5Engine.license_info, LicenseInfo)
    assert isinstance(XTTSEngine.license_info, LicenseInfo)


def test_entry_point_plugin(fake_plugin) -> None:
    names = engine_names()
    assert "fake" in names and "broken" in names and "nolicense" in names
    assert names.count("f5") == 1  # a plugin cannot impersonate a built-in engine
    eng = get_engine("fake")
    assert isinstance(eng, FakeEngine) and get_engine("FAKE") is eng
    assert get_engine("fake", gain=0.5).gain == 0.5
    # Scripts accept the plugin engine
    script = parse_script("---\nengine: fake\n---\n[voice:ana engine=fake] Hello")
    assert script.meta.default_engine == "fake"

    info = engine_info(check_cuda=False)
    assert info["fake"]["source"] == "plugin"
    assert info["fake"]["kind"] == "cloud"
    assert info["fake"]["license"] == "MIT" and info["fake"]["commercial_use"] is True
    assert info["fake"]["configured"] is False
    assert info["fake"]["missing_config"] == ["FAKE_TTS_KEY"]
    assert info["broken"]["importable"] is False and "podcast_tts_no_existe" in info["broken"]["error"]
    # No license_info -> treated as non-commercial
    assert engine_license("nolicense").commercial_use is False
    assert info["nolicense"]["license"] == "not declared"

    with pytest.raises(EngineError, match="could not load engine 'broken'"):
        get_engine("broken")


def test_plugin_disappears_after_refresh(fake_plugin, monkeypatch) -> None:
    assert "fake" in engine_names()
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: metadata.EntryPoints([]))
    refresh_engines()
    assert "fake" not in engine_names()
    with pytest.raises(ScriptParseError, match="unknown engine 'fake'"):
        parse_script("[voice:ana engine=fake] Hello")


def test_register_engine_runtime() -> None:
    register_engine("mio", FakeEngine)
    try:
        assert "mio" in engine_names()
        assert get_engine("mio").sample_rate == 16000
        with pytest.raises(EngineError, match="already an engine"):
            register_engine("mio", FakeEngine)
        register_engine("mio", "podcast_tts.engines.dummy:DummyEngine", replace=True)
        assert get_engine("mio").name == "dummy"
        with pytest.raises(EngineError, match="built-in"):
            register_engine("f5", FakeEngine)
    finally:
        unregister_engine("mio")
    assert "mio" not in engine_names()


def test_register_engine_rejects_non_engines() -> None:
    register_engine("roto", lambda: object())
    try:
        with pytest.raises(EngineError, match="protocol"):
            get_engine("roto")
    finally:
        unregister_engine("roto")


def test_import_does_not_load_torch() -> None:
    """Importing engines (and querying the registry without a GPU) does not import torch."""
    code = (
        "import sys; sys.path.insert(0, r'%s'); import podcast_tts.engines as e; "
        "e.engine_names(); e.engine_info(check_cuda=False); import podcast_tts.cli; "
        "print('torch' in sys.modules)" % SRC
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_unknown_engine_message() -> None:
    with pytest.raises(EngineError, match="valid: f5, xtts, dummy, elevenlabs"):
        get_engine("nope")
