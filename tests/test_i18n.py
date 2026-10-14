"""Tests of the i18n module, the UI language selector and the launcher's message table."""

from __future__ import annotations

import importlib.util
import string
from pathlib import Path

import pytest

from podcast_tts import cli, i18n
from podcast_tts.i18n import t

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    monkeypatch.setenv("PODCAST_TTS_ENV_FILE", str(path))
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    i18n.reset_language()
    return path


# --------------------------------------------------------------------------- resolution


def test_default_is_english(env_file: Path) -> None:
    assert i18n.get_language() == "en"
    assert i18n.available_languages() == ("en", "es")
    assert t("ui.tab_script") == "Script → Podcast"


def test_saved_setting_beats_default(env_file: Path) -> None:
    env_file.write_text("PODCAST_TTS_LANG=es\n", encoding="utf-8")
    assert i18n.saved_language() == "es"
    assert i18n.get_language() == "es"
    assert t("ui.tab_script") == "Guion → Podcast"


def test_env_var_beats_saved_setting(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text("PODCAST_TTS_LANG=es\n", encoding="utf-8")
    monkeypatch.setenv(i18n.ENV_VAR, "en_US.UTF-8")
    assert i18n.get_language() == "en"
    i18n.reset_language()
    monkeypatch.setenv(i18n.ENV_VAR, "fr")  # unsupported -> ignored, falls back to .env
    assert i18n.get_language() == "es"


def test_language_is_cached_until_reset(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert i18n.get_language() == "en"
    monkeypatch.setenv(i18n.ENV_VAR, "es")
    assert i18n.get_language() == "en"
    i18n.reset_language()
    assert i18n.get_language() == "es"


def test_set_and_save_language(env_file: Path) -> None:
    assert i18n.set_language("ES") == "es" and i18n.get_language() == "es"
    assert not env_file.exists()  # not persisted by default
    i18n.save_language("es")
    assert "PODCAST_TTS_LANG=es" in env_file.read_text(encoding="utf-8")
    i18n.set_language("en", persist=True)
    assert i18n.saved_language() == "en" and i18n.get_language() == "en"
    with pytest.raises(ValueError):
        i18n.set_language("fr")
    with pytest.raises(ValueError):
        i18n.save_language("")


def test_no_os_locale_detection(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.setenv(var, "es_ES.UTF-8")
    assert i18n.get_language() == "en"


# --------------------------------------------------------------------------- fallbacks


def test_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    assert t("no.such.key") == "no.such.key"
    monkeypatch.setitem(i18n.CATALOG, "test.only_en", {"en": "only English"})
    i18n.set_language("es")
    assert t("test.only_en") == "only English"
    assert t("ui.tab_voices", _lang="xx") == "Voices"  # unknown language -> English
    assert t("ui.tab_voices", _lang="es") == "Voces"
    assert t("cli.voice_saved", name="ana") == "Voz '{name}' guardada en {path}"  # bad kwargs


def test_formatting() -> None:
    assert t("cli.done_duration", path="o.mp3", duration=12.34, elapsed=5.0) == \
        "Done: o.mp3 — duration 12.3 s, generated in 5.0 s"
    assert t("cli.done_duration", _lang="es", path="o.mp3", duration=12.34, elapsed=5.0) == \
        "Listo: o.mp3 — duración 12.3 s, generado en 5.0 s"


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_key_has_both_languages_with_same_placeholders() -> None:
    assert len(i18n.CATALOG) > 100
    for key, entry in i18n.CATALOG.items():
        assert set(entry) == {"en", "es"}, key
        assert entry["en"].strip() and entry["es"].strip(), key
        assert _fields(entry["en"]) == _fields(entry["es"]), key


def test_every_key_used_in_code_exists() -> None:
    import re

    used: set[str] = set()
    for path in (ROOT / "src" / "podcast_tts").rglob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["']([a-z]+\.[A-Za-z_]+)["']""",
                               path.read_text(encoding="utf-8")))
    assert used, "no t() calls found"
    assert used - set(i18n.CATALOG) == set()


# --------------------------------------------------------------------------- CLI / UI


def test_cli_follows_language(env_file: Path, capsys, monkeypatch: pytest.MonkeyPatch,
                              tmp_path: Path) -> None:
    vdir = tmp_path / "voices"
    assert cli.main(["voices", "list", "--voices-dir", str(vdir)]) == 0
    assert "No voices in" in capsys.readouterr().out
    monkeypatch.setenv(i18n.ENV_VAR, "es")
    i18n.reset_language()
    assert cli.main(["voices", "list", "--voices-dir", str(vdir)]) == 0
    assert "No hay voces en" in capsys.readouterr().out
    assert cli.main(["parse", str(tmp_path / "missing.md")]) == 1
    assert "fichero no encontrado" in capsys.readouterr().err


def test_cli_config_set_language(env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "Español")
    assert cli.main(["config", "set", "PODCAST_TTS_LANG"]) == 1  # not a language code
    monkeypatch.setattr("builtins.input", lambda prompt="": "es_ES")
    assert cli.main(["config", "set", "PODCAST_TTS_LANG"]) == 0
    out = capsys.readouterr()
    assert "not a known variable" not in out.err and "(es)" in out.out
    assert i18n.saved_language() == "es"


def test_ui_language_selector(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("gradio")
    from podcast_tts import ui

    assert i18n.get_language() == "en"  # the running app resolved its language at startup
    assert ui.language_choices() == [("English", "en"), ("Español", "es")]
    msg = ui.save_ui_language("es")
    assert "Español" in msg and "Restart" in msg and "precedence" not in msg
    assert i18n.saved_language() == "es"
    assert i18n.get_language() == "en"  # the running app keeps its language
    assert "⚠️" in ui.save_ui_language("klingon")
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    assert "takes precedence" in ui.save_ui_language("es")


def _component_labels(app) -> set[str]:
    labels = set()
    for block in app.blocks.values():
        for attr in ("label", "value"):
            value = getattr(block, attr, None)
            if isinstance(value, str):
                labels.add(value)
    return labels


def test_ui_builds_in_each_language(env_file: Path, monkeypatch: pytest.MonkeyPatch,
                                    tmp_path: Path) -> None:
    pytest.importorskip("gradio")
    from podcast_tts import ui

    cfg = ui.UIConfig(voices_dir=tmp_path / "v", output_dir=tmp_path / "o", cache_dir=None,
                      scripts_dir=tmp_path / "g", script_base_dir=tmp_path)
    labels = _component_labels(ui.build_app(cfg))
    assert {"Script → Podcast", "Voices", "System", "Settings"} <= labels
    assert ui.default_script_path().name == "english_episode.md"
    assert ui.default_script_path("es").name == "ejemplo.md"
    assert "[voice:name]" in ui.help_markdown()

    monkeypatch.setenv(i18n.ENV_VAR, "es")
    i18n.reset_language()
    labels = _component_labels(ui.build_app(cfg))
    assert {"Guion → Podcast", "Voces", "Sistema", "Ajustes"} <= labels
    assert ui.default_script_path().name == "ejemplo.md"
    assert ui.segment_headers()[1] == "Tipo"


def test_ui_accepts_old_auto_label(tmp_path: Path) -> None:
    pytest.importorskip("gradio")
    from podcast_tts import ui

    assert ui._engine_override("auto (según voz)") is None
    assert ui._engine_override(ui.ENGINE_AUTO) is None
    assert ui._engine_override("dummy") == "dummy"


# --------------------------------------------------------------------------- launcher


@pytest.fixture
def launcher():
    spec = importlib.util.spec_from_file_location("ag_launcher_i18n", ROOT / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_messages(launcher, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, (en, es) in launcher.MESSAGES.items():
        assert en.strip() and es.strip(), key
        assert _fields(en) == _fields(es), key
    monkeypatch.delenv("PODCAST_TTS_LANG", raising=False)
    assert launcher.ui_language() == "en"
    assert "local changes" in launcher.update_failure_message(launcher.UPDATE_PULL_FAILED)
    env_file.write_text('# x\nPODCAST_TTS_LANG="es"\n', encoding="utf-8")
    assert launcher.ui_language() == "es"
    assert "cambios locales" in launcher.update_failure_message(launcher.UPDATE_PULL_FAILED)
    monkeypatch.setenv("PODCAST_TTS_LANG", "en")
    assert launcher.ui_language() == "en"
