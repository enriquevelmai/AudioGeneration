"""Tests de la UI Gradio a través de sus funciones Python (sin navegador)."""

from __future__ import annotations

from pathlib import Path

import pytest

gr = pytest.importorskip("gradio")

from conftest import requires_ffmpeg, write_tone  # noqa: E402

from podcast_tts import ui  # noqa: E402
from podcast_tts.voices import add_voice  # noqa: E402

SCRIPT = """---
title: Prueba UI
lang: es
default_voice: ana
---
# comentario
[voz:ana] Hola, esto es una prueba. [pausa:0.3]
[voz:carlos lang=en] Hello there!
"""


@pytest.fixture
def cfg(tmp_path: Path) -> ui.UIConfig:
    return ui.UIConfig(
        voices_dir=tmp_path / "voices",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        scripts_dir=tmp_path / "guiones",
        script_base_dir=tmp_path,
    )


def test_build_app(cfg: ui.UIConfig) -> None:
    app = ui.build_app(cfg)
    assert isinstance(app, gr.Blocks)
    assert app.podcast_config is cfg


def test_validate_script_ok_and_missing_voices(cfg: ui.UIConfig) -> None:
    ui.build_app(cfg)
    df, report = ui.validate_script(SCRIPT, ui.ENGINE_AUTO, cfg)
    assert list(df.columns) == ui.SEGMENT_HEADERS
    tipos = list(df["Tipo"])
    assert tipos.count("Voz") == 2 and "Pausa" in tipos
    assert "en" in list(df["Idioma"])
    assert "Guion válido" in report
    assert "NO EXISTE" in report and "`ana`" in report and "`carlos`" in report
    # Con dummy, las voces que faltan no son un problema
    _, report_dummy = ui.validate_script(SCRIPT, "dummy", cfg)
    assert "NO EXISTE" not in report_dummy


def test_validate_script_error_with_line(cfg: ui.UIConfig) -> None:
    df, report = ui.validate_script("[voz:ana] Hola\n[pausa:abc]\n", ui.ENGINE_AUTO, cfg)
    assert df.empty
    assert "Error en el guion (línea 2)" in report


@pytest.mark.filterwarnings("ignore:el clip dura")
def test_validate_existing_voice(cfg: ui.UIConfig, tmp_path: Path) -> None:
    wav = write_tone(tmp_path / "clip.wav", 1.0)
    try:
        add_voice("ana", wav, "Hola", voices_dir=cfg.voices_dir, engine="dummy")
    except Exception as exc:  # pragma: no cover - sin ffmpeg
        pytest.skip(f"no se pudo crear la voz: {exc}")
    _, report = ui.validate_script(SCRIPT, ui.ENGINE_AUTO, cfg)
    assert "`ana`: idioma es, motor dummy, ref.wav" in report
    assert ui.voices_table(cfg)["Nombre"].tolist() == ["ana"]


@requires_ffmpeg
def test_generate_dummy(cfg: ui.UIConfig) -> None:
    calls: list[tuple[int, int, str]] = []
    path, summary = ui.run_generation(SCRIPT, "dummy", "prueba ui", "mp3", "128k", True, cfg,
                                      lambda i, n, m: calls.append((i, n, m)))
    assert path == cfg.output_dir / "prueba ui.mp3" and path.stat().st_size > 1000
    assert "Listo" in summary and calls


@requires_ffmpeg
def test_generate_events_dummy_and_errors(cfg: ui.UIConfig) -> None:
    events = list(ui.generate_events(SCRIPT, "dummy", "ep", "wav", "192k", False, cfg))
    audio, file, log = events[-1]
    assert audio == file == str(cfg.output_dir / "ep.wav")
    assert Path(audio).is_file()
    assert "✅" in log and "Sintetizando" in log
    assert ui.output_files(cfg) == [str(cfg.output_dir / "ep.wav")]

    # Voz inexistente con motor real -> error en castellano, sin excepción
    *_, (audio, file, log) = ui.generate_events(SCRIPT, "f5", "ep2", "mp3", "192k", True, cfg)
    assert audio is None and file is None
    assert "❌" in log and "no existe" in log

    # Error de sintaxis con línea
    *_, (_, _, log) = ui.generate_events("[pausa:x]", "dummy", "ep3", "mp3", "192k", True, cfg)
    assert "Error en el guion (línea 1)" in log


def test_save_script_and_cache(cfg: ui.UIConfig) -> None:
    path, msg = ui.save_script(SCRIPT, "mi guion/../raro", cfg)
    assert path is not None and Path(path).parent == cfg.scripts_dir
    assert Path(path).read_text(encoding="utf-8") == SCRIPT
    assert ui.save_script("  ", "x", cfg)[0] is None

    cfg.cache_dir.mkdir(parents=True)
    (cfg.cache_dir / "a.npz").write_bytes(b"x" * 10)
    assert "1 frases" in ui.clear_cache(cfg)
    assert not any(cfg.cache_dir.iterdir())


def test_create_and_delete_voice_errors(cfg: ui.UIConfig) -> None:
    assert "nombre" in ui.create_voice("", None, "", "es", "f5", "", 1.0, None, False, cfg)
    assert "audio" in ui.create_voice("x", None, "", "es", "f5", "", 1.0, None, False, cfg)
    msg = ui.create_voice("narr", None, "", "en", "f5", "", 1.0, "Claribel Dervla", False, cfg)
    assert "✅" in msg
    assert ui.voices_table(cfg)["Motor"].tolist() == ["xtts"]
    assert "eliminada" in ui.delete_voice("narr", cfg)
    assert "❌" in ui.delete_voice("narr", cfg)
