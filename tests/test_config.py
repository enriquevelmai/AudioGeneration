"""Configuración de claves (.env en tmp_path, sin tocar el .env real)."""

from __future__ import annotations

import pytest

from podcast_tts import config

KEYS = ("ELEVENLABS_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "OPENAI_API_KEY")


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / ".env"
    monkeypatch.setenv("PODCAST_TTS_ENV_FILE", str(path))
    return path


def test_default_path_is_project_root(monkeypatch) -> None:
    monkeypatch.delenv("PODCAST_TTS_ENV_FILE", raising=False)
    assert config.env_file_path() == config.PROJECT_ROOT / ".env"
    gitignore = (config.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore
    example = (config.PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert all(f"{k}=\n" in example for k in KEYS)


def test_set_get_delete(env_file) -> None:
    assert config.get_key("OPENAI_API_KEY") is None
    config.set_key("OPENAI_API_KEY", "sk-abc123456789xyz")
    config.set_key("AZURE_SPEECH_REGION", "westeurope")
    assert config.get_key("OPENAI_API_KEY") == "sk-abc123456789xyz"
    # Sustituye sin duplicar
    config.set_key("OPENAI_API_KEY", "sk-new-value-0000wxyz")
    text = env_file.read_text(encoding="utf-8")
    assert text.count("OPENAI_API_KEY=") == 1 and "sk-new-value-0000wxyz" in text
    assert config.read_env_file() == {"OPENAI_API_KEY": "sk-new-value-0000wxyz",
                                      "AZURE_SPEECH_REGION": "westeurope"}
    assert config.delete_key("OPENAI_API_KEY") is True
    assert config.delete_key("OPENAI_API_KEY") is False
    assert config.get_key("OPENAI_API_KEY") is None
    assert config.get_key("AZURE_SPEECH_REGION") == "westeurope"


def test_env_var_has_priority(env_file, monkeypatch) -> None:
    config.set_key("ELEVENLABS_API_KEY", "from-file-123456789")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env-987654321")
    assert config.get_key("ELEVENLABS_API_KEY") == "from-env-987654321"
    st = {s.name: s for s in config.key_status()}
    assert st["ELEVENLABS_API_KEY"].source == "entorno"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "  ")  # vacía -> se ignora
    assert config.get_key("ELEVENLABS_API_KEY") == "from-file-123456789"


def test_parse_existing_file_keeps_comments(env_file) -> None:
    env_file.write_text(
        "# comentario\n"
        "export OPENAI_API_KEY='sk-quoted value'\n"
        'AZURE_SPEECH_KEY="abc\\"def"\n'
        "AZURE_SPEECH_REGION=westeurope # región\n"
        "EMPTY=\n"
        "basura sin igual\n",
        encoding="utf-8",
    )
    data = config.read_env_file()
    assert data["OPENAI_API_KEY"] == "sk-quoted value"
    assert data["AZURE_SPEECH_KEY"] == 'abc"def'
    assert data["AZURE_SPEECH_REGION"] == "westeurope"
    assert config.get_key("EMPTY") is None
    config.set_key("ELEVENLABS_API_KEY", 'va"lor con espacios')
    assert config.get_key("ELEVENLABS_API_KEY") == 'va"lor con espacios'
    text = env_file.read_text(encoding="utf-8")
    assert text.startswith("# comentario\n") and "basura sin igual" in text


def test_validation(env_file) -> None:
    with pytest.raises(config.ConfigError):
        config.set_key("bad name", "x")
    with pytest.raises(config.ConfigError):
        config.set_key("OPENAI_API_KEY", "")
    with pytest.raises(config.ConfigError):
        config.set_key("OPENAI_API_KEY", "a\nb")
    assert not env_file.exists()


def test_mask_and_status(env_file) -> None:
    assert config.mask("sk-proj-1234567890abcd") == "sk-...abcd"
    assert config.mask("short") == "****"
    assert config.mask("") == "" and config.mask(None) == ""
    config.set_key("OPENAI_API_KEY", "sk-proj-1234567890abcd")
    config.set_key("AZURE_SPEECH_REGION", "westeurope")
    st = {s.name: s for s in config.key_status()}
    assert st["OPENAI_API_KEY"].masked == "sk-...abcd" and st["OPENAI_API_KEY"].source == ".env"
    assert st["AZURE_SPEECH_REGION"].masked == "westeurope"  # no es secreta
    assert not st["ELEVENLABS_API_KEY"].is_set and st["ELEVENLABS_API_KEY"].masked == ""
    assert "1234567890" not in repr(st)
