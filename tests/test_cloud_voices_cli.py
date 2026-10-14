"""Voces de motores en la nube, CLI (engines, config, voices add) y funciones de la UI."""

from __future__ import annotations

import json

import pytest

from podcast_tts import cli
from podcast_tts.voices import Voice, VoiceError, add_voice, get_voice, list_voices

FAKE_KEY = "sk-test-abcdefghijklmnop"
KEYS = ("ELEVENLABS_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PODCAST_TTS_ENV_FILE", str(tmp_path / ".env"))


# --------------------------------------------------------------------------- voces


def test_add_cloud_voice_without_wav(tmp_path) -> None:
    vdir = tmp_path / "voices"
    v = add_voice("narradora", None, lang="es", engine="azure",
                  provider_voice_id="es-ES-ElviraNeural",
                  provider_options={"style": "cheerful"}, voices_dir=vdir)
    assert not v.has_ref and not (vdir / "narradora" / "ref.txt").exists()
    data = json.loads((vdir / "narradora" / "voice.json").read_text(encoding="utf-8"))
    assert data["provider_voice_id"] == "es-ES-ElviraNeural"
    assert data["provider_options"] == {"style": "cheerful"}
    loaded = get_voice("narradora", vdir)
    assert loaded.engine == "azure" and loaded.provider_voice_id == "es-ES-ElviraNeural"
    assert loaded.provider_options == {"style": "cheerful"} and loaded.extra == {}
    assert [x.name for x in list_voices(vdir)] == ["narradora"]


def test_cloud_voice_requires_provider_id(tmp_path) -> None:
    with pytest.raises(VoiceError, match="provider_voice_id"):
        add_voice("x", None, engine="openai", voices_dir=tmp_path)
    with pytest.raises(VoiceError, match="motor desconocido"):
        add_voice("x", None, engine="noexiste", provider_voice_id="a", voices_dir=tmp_path)
    with pytest.raises(VoiceError, match="diccionario"):
        add_voice("x", None, engine="openai", provider_voice_id="nova",
                  provider_options=["no"], voices_dir=tmp_path)  # type: ignore[arg-type]


def test_fingerprint_includes_provider_data(tmp_path) -> None:
    base = Voice("a", tmp_path / "a", engine="openai", provider_voice_id="nova")
    other_id = Voice("a", tmp_path / "a", engine="openai", provider_voice_id="alloy")
    other_opts = Voice("a", tmp_path / "a", engine="openai", provider_voice_id="nova",
                       provider_options={"model": "tts-1"})
    assert len({base.fingerprint(), other_id.fingerprint(), other_opts.fingerprint()}) == 3
    # Las voces locales conservan la huella de siempre (no se invalida la caché existente)
    local = Voice("b", tmp_path / "b", engine="xtts", xtts_speaker="Ana Florence")
    assert local.fingerprint() == "b|xtts|Ana Florence|"
    assert "provider_voice_id" not in local.to_dict()


def test_invalid_provider_options_in_json(tmp_path) -> None:
    d = tmp_path / "rara"
    d.mkdir()
    (d / "voice.json").write_text('{"engine": "openai", "provider_options": [1]}', encoding="utf-8")
    with pytest.raises(VoiceError, match="provider_options"):
        get_voice("rara", tmp_path)


# --------------------------------------------------------------------------- CLI


def test_cli_engines(capsys) -> None:
    assert cli.main(["engines"]) == 0
    out = capsys.readouterr().out
    for name in ("f5", "xtts", "dummy", "elevenlabs", "azure", "openai"):
        assert name in out
    assert "CC-BY-NC-4.0" in out and "sin configurar" in out
    assert cli.main(["engines", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["f5"]["commercial_use"] is False
    assert data["openai"]["kind"] == "cloud" and data["openai"]["configured"] is False


def test_cli_config_set_show_unset(capsys, monkeypatch, tmp_path) -> None:
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": FAKE_KEY)
    assert cli.main(["config", "set", "OPENAI_API_KEY"]) == 0
    out = capsys.readouterr().out
    assert FAKE_KEY not in out and "sk-...mnop" in out
    assert FAKE_KEY in (tmp_path / ".env").read_text(encoding="utf-8")

    monkeypatch.setattr("builtins.input", lambda prompt="": "westeurope")
    assert cli.main(["config", "set", "AZURE_SPEECH_REGION"]) == 0
    capsys.readouterr()

    assert cli.main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert FAKE_KEY not in out
    assert "sk-...mnop (.env)" in out and "westeurope" in out and "(sin definir)" in out

    assert cli.main(["config", "unset", "OPENAI_API_KEY"]) == 0
    assert "borrada" in capsys.readouterr().out
    assert FAKE_KEY not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_cli_config_set_never_accepts_value_argument(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["config", "set", "OPENAI_API_KEY", FAKE_KEY])


def test_cli_voices_add_cloud(tmp_path, capsys) -> None:
    vdir = tmp_path / "voices"
    rc = cli.main(["voices", "add", "nova", "--engine", "openai", "--provider-voice-id", "nova",
                   "--provider-option", "model=tts-1-hd", "--provider-option", "speed_hint=1.5",
                   "--voices-dir", str(vdir)])
    assert rc == 0
    v = get_voice("nova", vdir)
    assert v.provider_voice_id == "nova"
    assert v.provider_options == {"model": "tts-1-hd", "speed_hint": 1.5}
    assert cli.main(["voices", "list", "--voices-dir", str(vdir)]) == 0
    assert "voz del proveedor 'nova'" in capsys.readouterr().out
    # Sin ID -> error en castellano, código 1
    assert cli.main(["voices", "add", "otra", "--engine", "elevenlabs",
                     "--voices-dir", str(vdir)]) == 1
    assert "provider_voice_id" in capsys.readouterr().err


def test_cli_license_notice(tmp_path, capsys, monkeypatch) -> None:
    script = tmp_path / "g.md"
    script.write_text("[voz:ana] Hola.\n", encoding="utf-8")
    vdir = tmp_path / "voices"
    add_voice("ana", None, engine="xtts", xtts_speaker="Ana Florence", voices_dir=vdir)

    called = []
    monkeypatch.setattr("podcast_tts.assembler.generate",
                        lambda *a, **k: called.append(1) or tmp_path / "o.mp3")
    args = ["generate", str(script), "-o", str(tmp_path / "o.mp3"), "--voices-dir", str(vdir)]
    assert cli.main(args) == 0
    err = capsys.readouterr().err
    assert err.count("Aviso de licencia") == 1 and "'xtts'" in err and "NO comercial" in err
    assert cli.main([*args, "--no-license-notice"]) == 0
    assert "Aviso de licencia" not in capsys.readouterr().err
    assert cli.main([*args, "--engine", "dummy"]) == 0
    assert "Aviso de licencia" not in capsys.readouterr().err
    assert len(called) == 3


# --------------------------------------------------------------------------- UI


def test_ui_settings_and_cloud_voice(tmp_path) -> None:
    pytest.importorskip("gradio")
    from podcast_tts import ui

    cfg = ui.UIConfig(voices_dir=tmp_path / "voices", output_dir=tmp_path / "out",
                      cache_dir=tmp_path / "cache", scripts_dir=tmp_path / "g",
                      script_base_dir=tmp_path)
    assert "openai" in ui.engine_choices() and ui.engine_choices()[0] == ui.ENGINE_AUTO

    assert "⚠️" in ui.save_api_key("OPENAI_API_KEY", "")
    msg = ui.save_api_key("OPENAI_API_KEY", FAKE_KEY)
    assert "✅" in msg and FAKE_KEY not in msg
    status = ui.settings_status()
    assert "sk-...mnop" in status and FAKE_KEY not in status
    df = ui.engines_table()
    row = df[df["Motor"] == "openai"].iloc[0]
    assert row["Configurado"] == "sí" and row["Tipo"] == "nube"
    assert df[df["Motor"] == "f5"].iloc[0]["Uso comercial"] == "no"
    assert "borrada" in ui.delete_api_key("OPENAI_API_KEY")

    assert "ID de la voz" in ui.create_voice("v1", None, "", "es", "openai", "", 1.0, None,
                                              False, cfg)
    ok = ui.create_voice("v1", None, "", "es", "openai", "", 1.0, None, False, cfg,
                         provider_voice_id="nova")
    assert "✅" in ok
    assert ui.voices_table(cfg)["ID proveedor"].tolist() == ["nova"]

    script = "[voz:v1] Hola"
    assert ui.generation_license_notice(script, ui.ENGINE_AUTO, cfg) == ""
    assert "NO comercial" in ui.generation_license_notice(script, "xtts", cfg)
    assert "NO comercial" in ui.generation_license_notice("", "f5", cfg)
    assert ui.generation_license_notice("[voz:", ui.ENGINE_AUTO, cfg) == ""
    _, report = ui.validate_script(script, ui.ENGINE_AUTO, cfg)
    assert "voz del proveedor 'nova'" in report
