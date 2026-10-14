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


# --------------------------------------------------------------------------- #
# Regresiones de la revisión de código: modo remoto y autenticación
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("host, loopback", [
    ("127.0.0.1", True), ("localhost", True), ("::1", True), ("[::1]", True), ("127.0.0.2", True),
    ("0.0.0.0", False), ("192.168.1.10", False), ("::", False), ("mi-pc", False), ("", False),
])
def test_is_loopback_host(host: str, loopback: bool) -> None:
    assert ui.is_loopback_host(host) is loopback


def test_resolve_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ui.AUTH_ENV, raising=False)
    assert ui.resolve_auth("127.0.0.1", False) == (False, None)
    with pytest.raises(ui.RemoteAuthError, match="--auth"):
        ui.resolve_auth("0.0.0.0", False)
    with pytest.raises(ui.RemoteAuthError, match="--share"):
        ui.resolve_auth("127.0.0.1", True)
    assert ui.resolve_auth("0.0.0.0", False, "ana:se:creta") == (True, ("ana", "se:creta"))
    for bad in ("solo_usuario", ":clave", "usuario:"):
        with pytest.raises(ui.RemoteAuthError, match="formato"):
            ui.resolve_auth("0.0.0.0", False, bad)
    monkeypatch.setenv(ui.AUTH_ENV, "env:clave")
    assert ui.resolve_auth("0.0.0.0", True) == (True, ("env", "clave"))


def test_run_from_args_refuses_remote_without_auth(monkeypatch, capsys) -> None:
    monkeypatch.delenv(ui.AUTH_ENV, raising=False)
    launched: list = []
    monkeypatch.setattr(ui, "launch", lambda *a, **k: launched.append(k))
    args = ui.build_arg_parser().parse_args(["--host", "0.0.0.0"])
    assert ui.run_from_args(args) == 2
    assert "usuario y clave" in capsys.readouterr().err
    assert launched == []
    args = ui.build_arg_parser().parse_args(["--share"])
    assert ui.run_from_args(args) == 2
    args = ui.build_arg_parser().parse_args(["--host", "0.0.0.0", "--auth", "u:p"])
    assert ui.run_from_args(args) == 0
    assert launched[0]["auth"] == ("u", "p") and launched[0]["cfg"].remote is True


def test_cli_ui_accepts_auth(monkeypatch) -> None:
    from podcast_tts import cli

    monkeypatch.delenv(ui.AUTH_ENV, raising=False)
    seen: list = []
    monkeypatch.setattr(ui, "launch", lambda *a, **k: seen.append(k))
    assert cli.main(["ui", "--host", "0.0.0.0"]) == 2
    assert cli.main(["ui", "--host", "0.0.0.0", "--auth", "u:p"]) == 0
    assert seen[0]["auth"] == ("u", "p")


def test_launch_passes_auth_and_refuses_local_app(monkeypatch, cfg: ui.UIConfig) -> None:
    monkeypatch.delenv(ui.AUTH_ENV, raising=False)
    calls: list = []
    monkeypatch.setattr(gr.Blocks, "launch", lambda self, **k: calls.append(k))
    local_app = ui.build_app(cfg)
    with pytest.raises(ui.RemoteAuthError):
        ui.launch(local_app, host="0.0.0.0", cfg=cfg, auth="u:p")  # app construida en modo local
    with pytest.raises(ui.RemoteAuthError):
        ui.launch(local_app, host="0.0.0.0", cfg=cfg)
    ui.launch(local_app, host="127.0.0.1", cfg=cfg)
    assert calls[-1]["auth"] is None
    cfg.remote = True
    ui.launch(ui.build_app(cfg), host="0.0.0.0", cfg=cfg, auth="u:p")
    assert calls[-1]["auth"] == ("u", "p")


def _fn_names(app) -> set[str]:
    return {getattr(f.fn, "__name__", "") for f in app.fns.values()}


def test_internal_events_are_private(cfg: ui.UIConfig) -> None:
    app = ui.build_app(cfg)
    public = {f.api_name for f in app.fns.values() if f.api_visibility != "private"}
    assert public == {"validar", "generar", "probar_voz"}
    assert {"_save_key", "_delete_key", "_do_delete", "_add"} <= _fn_names(app)


def test_remote_mode_hides_settings_and_external_paths(cfg: ui.UIConfig, tmp_path: Path) -> None:
    cfg.remote = True
    app = ui.build_app(cfg)
    assert not {"_save_key", "_delete_key"} & _fn_names(app)
    write_tone(tmp_path / "fuera" / "x.wav", 0.3, channels=1)
    absolute = tmp_path / "fuera" / "x.wav"
    for raw in (str(absolute), "../fuera/x.wav"):
        *_, (_, _, log) = ui.generate_events(f'[voz:a] hola\n[sfx:"{raw}"]', "dummy", "ep",
                                             "wav", "192k", False, cfg)
        assert "no permitida" in log
    assert "modo remoto" in ui.open_output_folder(cfg, opener=lambda p: None)


def test_display_path_is_relative_to_project() -> None:
    assert ui.display_path(ui.PROJECT_ROOT / "output" / "x.mp3") == str(Path("output/x.mp3"))
    assert ui.display_path("Z:/fuera/x.mp3") == str(Path("Z:/fuera/x.mp3"))
    assert ui.display_path(None) == ""
