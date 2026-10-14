"""Local web UI (Gradio) to generate podcasts and manage voices.

Launch with::

    python -m podcast_tts ui [--port 7860] [--host 127.0.0.1] [--share] [--auth user:password]

Outside 127.0.0.1/localhost/::1, or with ``--share``, the UI requires a user and password
(``--auth`` or the ``PODCAST_TTS_AUTH`` variable) and runs in *remote mode*: no Settings tab
(API keys) and no absolute or ``..`` audio paths.

The app starts without loading any model: F5-TTS / XTTS are loaded lazily on the first
synthesis (``engines.get_engine``). The engine list is dynamic (built-in, cloud and plugins;
see ``engines.engine_names``).

All texts go through :mod:`podcast_tts.i18n` (English by default, Spanish optional). The
language is fixed when the app is built; the selector in the Settings tab saves it for the
next start.

The logic lives in plain Python functions (``validate_script``, ``run_generation``,
``generate_events``, ``voices_table``...) that receive a :class:`UIConfig`, so they can be
tested without a browser.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import queue
import re
import threading
import time
import warnings
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

import gradio as gr
import pandas as pd

from .assembler import (
    DEFAULT_CACHE_DIR,
    AssembleError,
    AssembleOptions,
    assemble,
    export_audio,
    synthesize_speech,
)
from . import config as config_mod
from . import i18n
from ._warnings import silence_noisy_warnings
from .engines import EngineError, engine_info, engine_kind, engine_names
from .i18n import t
from .licensing import engines_in_script, license_notice
from .script_parser import (
    DEFAULT_MAX_CHARS,
    Music,
    ParsedScript,
    Pause,
    ScriptParseError,
    Sfx,
    Speech,
    parse_script,
)
from .voices import (
    PROJECT_ROOT,
    VoiceError,
    add_voice,
    default_voices_dir,
    get_voice,
    list_voices,
    remove_voice,
)

__all__ = [
    "AUTH_ENV",
    "ENGINE_AUTO",
    "RemoteAuthError",
    "UIConfig",
    "build_app",
    "clear_cache",
    "default_script_path",
    "delete_api_key",
    "delete_voice",
    "display_path",
    "engine_choices",
    "engine_headers",
    "engines_table",
    "format_error",
    "generate_events",
    "generation_license_notice",
    "help_markdown",
    "is_loopback_host",
    "language_choices",
    "main",
    "parse_auth",
    "resolve_auth",
    "open_output_folder",
    "output_files",
    "run_generation",
    "save_api_key",
    "save_script",
    "save_ui_language",
    "segment_headers",
    "settings_status",
    "system_status",
    "test_voice",
    "validate_script",
    "voice_headers",
    "voices_table",
]

#: Value of the "use each voice's engine" option in the engine selectors.
ENGINE_AUTO = "auto"


def engine_choices() -> list[str]:
    """Choices of the engine selector: "auto" + registered engines (dynamic)."""
    return [ENGINE_AUTO, *engine_names()]


def _is_auto(choice: str | None) -> bool:
    # Also accepts the old Spanish label "auto (según voz)" sent by older API clients.
    return not choice or str(choice).strip().lower().startswith(ENGINE_AUTO)


def _is_cloud(engine: str | None) -> bool:
    if _is_auto(engine):
        return False
    try:
        return engine_kind(str(engine)) == "cloud"
    except EngineError:
        return False


ENGINE_CHOICES = engine_choices()  # value at import time (compatibility); the app uses engine_choices()
LANG_CHOICES = ["en", "es", "fr", "de", "it", "pt", "pl", "nl", "ca", "ja", "zh"]
BITRATES = ["96k", "128k", "160k", "192k", "256k", "320k"]
TEST_PHRASES = {
    "es": "Hola, esta es una prueba de mi voz para el podcast.",
    "en": "Hello, this is a quick test of my voice for the podcast.",
    "fr": "Bonjour, ceci est un essai de ma voix pour le podcast.",
    "de": "Hallo, das ist ein kurzer Test meiner Stimme für den Podcast.",
    "it": "Ciao, questa è una prova della mia voce per il podcast.",
    "pt": "Olá, este é um teste da minha voz para o podcast.",
    "ca": "Hola, això és una prova de la meva veu per al pòdcast.",
}
#: Example script loaded in the editor, per UI language.
EXAMPLE_SCRIPTS = {
    "en": PROJECT_ROOT / "examples" / "english_episode.md",
    "es": PROJECT_ROOT / "examples" / "ejemplo.md",
}

# Models are not thread-safe: one synthesis at a time.
_SYNTH_LOCK = threading.Lock()


def default_script_path(lang: str | None = None) -> Path:
    """Example script for the editor: the English one, or the Spanish one if the UI is in es."""
    return EXAMPLE_SCRIPTS.get(lang or i18n.get_language(), EXAMPLE_SCRIPTS["en"])


def help_markdown() -> str:
    """Help table with the script tags (English tags are canonical, Spanish ones aliases)."""
    return t("ui.help_md")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass
class UIConfig:
    """Paths used by the UI (they can be changed for tests)."""

    voices_dir: Path = field(default_factory=default_voices_dir)
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    cache_dir: Path | None = field(default_factory=lambda: DEFAULT_CACHE_DIR)
    scripts_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "guiones")
    script_base_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "examples")
    max_chars: int = DEFAULT_MAX_CHARS
    # Remote mode (UI reachable from other computers): no Settings tab and no external
    # audio paths. ``launch``/``run_from_args`` enable it depending on ``--host``/``--share``.
    remote: bool = False

    def __post_init__(self) -> None:
        self.voices_dir = Path(self.voices_dir)
        self.output_dir = Path(self.output_dir)
        self.cache_dir = Path(self.cache_dir) if self.cache_dir else None
        self.scripts_dir = Path(self.scripts_dir)
        self.script_base_dir = Path(self.script_base_dir)


def display_path(path: str | Path | None) -> str:
    """Path to show in the UI: relative to the project root when it is inside it.

    Avoids showing the user's full paths (``C:\\Users\\...``) on the page.
    """
    if path is None:
        return ""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(PROJECT_ROOT.resolve()))
    except (ValueError, OSError):
        return str(p)


def format_error(exc: BaseException) -> str:
    """Readable error message in the UI language."""
    if isinstance(exc, ScriptParseError):
        where = t("ui.err_line", line=exc.line) if exc.line else ""
        return t("ui.err_script", where=where, msg=exc.message)
    if isinstance(exc, AssembleError):
        return t("ui.err_assemble", exc=exc)
    if isinstance(exc, EngineError):
        return t("ui.err_engine", exc=exc)
    if isinstance(exc, VoiceError):
        return t("ui.err_voice", exc=exc)
    if isinstance(exc, NotImplementedError):
        return t("ui.err_not_implemented", exc=exc)
    if isinstance(exc, FileNotFoundError):
        return t("ui.err_file_not_found", file=exc.filename or exc)
    return t("ui.err_unexpected", type=type(exc).__name__, exc=exc)


def _engine_override(choice: str | None) -> str | None:
    if _is_auto(choice):
        return None
    return choice


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _safe_name(name: str, default: str = "episode") -> str:
    name = Path((name or "").strip()).stem or default
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip(" .")
    return name or default


# --------------------------------------------------------------------------- #
# Tab 1: script -> podcast
# --------------------------------------------------------------------------- #


def segment_headers() -> list[str]:
    """Column headers of the segments table."""
    return [t("ui.col_no"), t("ui.col_type"), t("ui.col_voice"), t("ui.col_language"),
            t("ui.col_text"), t("ui.col_line")]


def _segments_frame(script: ParsedScript, cfg: UIConfig) -> pd.DataFrame:
    voice_lang: dict[str, str] = {}
    for v in list_voices(cfg.voices_dir):
        voice_lang[v.name] = v.lang
    rows: list[list[Any]] = []
    for i, seg in enumerate(script.segments, start=1):
        if isinstance(seg, Speech):
            lang = seg.lang or script.meta.lang or voice_lang.get(seg.voice) or "es"
            extra = []
            if seg.speed:
                extra.append(f"speed={seg.speed:g}")
            if seg.engine:
                extra.append(f"engine={seg.engine}")
            voice = seg.voice + (f" ({', '.join(extra)})" if extra else "")
            rows.append([i, t("ui.seg_voice"), voice, lang, _short(seg.text), seg.line])
        elif isinstance(seg, Pause):
            rows.append([i, t("ui.seg_pause"), "", "", f"{seg.seconds:g} s", seg.line])
        elif isinstance(seg, Music):
            if seg.stop:
                rows.append([i, t("ui.seg_music_stop"), "", "", f"fade={seg.fade:g} s", seg.line])
            else:
                kind = t("ui.seg_music_bg") if seg.background else t("ui.seg_music")
                rows.append([i, kind, "", "", f"{seg.path} (vol={seg.volume:g})", seg.line])
        elif isinstance(seg, Sfx):
            rows.append([i, t("ui.seg_sfx"), "", "", f"{seg.path} (vol={seg.volume:g})", seg.line])
    return pd.DataFrame(rows, columns=segment_headers())


def validate_script(text: str, engine_choice: str | None, cfg: UIConfig
                    ) -> tuple[pd.DataFrame, str]:
    """Parse the script. Returns (segments table, Markdown report)."""
    empty = pd.DataFrame([], columns=segment_headers())
    if not (text or "").strip():
        return empty, t("ui.script_empty")
    try:
        script = parse_script(text, max_chars=cfg.max_chars)
    except ScriptParseError as exc:
        return empty, f"❌ {format_error(exc)}"
    override = _engine_override(engine_choice)
    n_speech = sum(isinstance(s, Speech) for s in script.segments)
    chars = sum(len(s.text) for s in script.segments if isinstance(s, Speech))
    lines = [t("ui.script_valid", segments=len(script.segments), speech=n_speech, chars=chars)]
    if script.meta.title:
        lines.append(t("ui.title", title=script.meta.title))
    lines.append("")
    lines.append(t("ui.voices_used"))
    missing = []
    for name in script.voices:
        try:
            voice = get_voice(name, cfg.voices_dir)
        except VoiceError:
            missing.append(name)
            if override == "dummy":
                lines.append(t("ui.voice_missing_dummy", name=name))
            else:
                lines.append(t("ui.voice_missing", name=name, dir=display_path(cfg.voices_dir)))
            continue
        engine = override or script.meta.default_engine or voice.engine
        if voice.provider_voice_id:
            src = t("ui.provider_voice", id=voice.provider_voice_id)
        else:
            src = "ref.wav" if voice.has_ref else (
                t("ui.xtts_speaker_src", speaker=voice.xtts_speaker) if voice.xtts_speaker
                else t("ui.no_ref"))
        lines.append(t("ui.voice_line", name=name, lang=voice.lang, engine=engine, src=src))
    if not script.voices:
        lines.append(t("ui.none"))
    if missing and override != "dummy":
        lines.append("")
        lines.append(t("ui.voices_missing_hint", n=len(missing)))
    notice = license_notice(engines_in_script(script, cfg.voices_dir, override), markdown=True)
    if notice:
        lines += ["", f"ℹ️ {notice}"]
    return _segments_frame(script, cfg), "\n".join(lines)


def generation_license_notice(text: str, engine_choice: str | None, cfg: UIConfig) -> str:
    """Discreet notice (Markdown) if the chosen engine, or the one the script's voices will use
    in auto mode, is non-commercial. Empty string if there is nothing to report."""
    override = _engine_override(engine_choice)
    names: list[str] = [override] if override else []
    if not override and (text or "").strip():
        try:
            names = engines_in_script(parse_script(text, max_chars=cfg.max_chars),
                                      cfg.voices_dir)
        except Exception:  # noqa: BLE001 - script still being written
            names = []
    notice = license_notice(names, markdown=True)
    return f"<small>ℹ️ {notice} {t('ui.license_more')}</small>" if notice else ""


def run_generation(
    text: str,
    engine_choice: str | None,
    out_name: str,
    fmt: str,
    bitrate: str,
    normalize: bool,
    cfg: UIConfig,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[Path, str]:
    """Generate the episode synchronously. Returns (path, summary). Raises exceptions."""
    if not (text or "").strip():
        raise AssembleError("the script is empty")
    fmt = (fmt or "mp3").lower().lstrip(".")
    if fmt not in ("mp3", "wav"):
        raise AssembleError(f"unsupported format: {fmt}")
    started = time.perf_counter()
    script = parse_script(text, max_chars=cfg.max_chars)
    options = AssembleOptions(
        engine_override=_engine_override(engine_choice),
        target_lufs=-16.0 if normalize else None,
        cache_dir=cfg.cache_dir,
        base_dir=cfg.script_base_dir,
        allow_external_paths=not cfg.remote,
    )
    output = cfg.output_dir / f"{_safe_name(out_name)}.{fmt}"
    with _SYNTH_LOCK:
        audio = assemble(script, voices_dir=cfg.voices_dir, options=options, progress=progress)
    tags = {"title": script.meta.title} if script.meta.title else None
    path = export_audio(audio, output, bitrate=bitrate or "192k", tags=tags)
    elapsed = time.perf_counter() - started
    summary = t("ui.done", path=display_path(path), duration=len(audio) / 1000, elapsed=elapsed)
    return path, summary


def generate_events(
    text: str,
    engine_choice: str | None,
    out_name: str,
    fmt: str,
    bitrate: str,
    normalize: bool,
    cfg: UIConfig,
    progress: Any = None,
) -> Iterator[tuple[Any, Any, str]]:
    """Generator for the UI: runs :func:`run_generation` in a thread and yields
    ``(audio, file, log)`` as it goes. Errors are shown in the log."""
    events: "queue.Queue[tuple]" = queue.Queue()
    result: dict[str, Any] = {}

    def callback(i: int, n: int, msg: str) -> None:
        events.put(("p", i, n, msg))

    def worker() -> None:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                silence_noisy_warnings()
                result["value"] = run_generation(text, engine_choice, out_name, fmt, bitrate,
                                                 normalize, cfg, callback)
            result["warnings"] = [str(w.message) for w in caught]
        except BaseException as exc:  # noqa: BLE001 - shown to the user
            result["error"] = exc
        finally:
            events.put(("done",))

    log = [t("ui.log_start", engine=engine_choice or ENGINE_AUTO)]
    thread = threading.Thread(target=worker, name="podcast-generate", daemon=True)
    thread.start()
    skip = gr.skip()
    yield skip, skip, "\n".join(log)
    done = False
    while not done:
        try:
            item = events.get(timeout=0.5)
        except queue.Empty:
            continue
        batch = [item]
        while True:  # group pending events so the UI is not flooded
            try:
                batch.append(events.get_nowait())
            except queue.Empty:
                break
        for ev in batch:
            if ev[0] == "done":
                done = True
                continue
            _, i, n, msg = ev
            log.append(f"[{i}/{n}] {msg}")
            if progress is not None:
                try:
                    progress((i, n), desc=msg)
                except Exception:  # outside a Gradio event
                    pass
        if not done:
            yield skip, skip, "\n".join(log)
    thread.join()
    for w in result.get("warnings", []):
        log.append(t("common.warning", msg=w))
    if "error" in result:
        log.append(f"❌ {format_error(result['error'])}")
        yield None, None, "\n".join(log)
        return
    path, summary = result["value"]
    log.append(f"✅ {summary}")
    yield str(path), str(path), "\n".join(log)


def load_script_file(file: Any) -> str:
    """Read an uploaded .md (a path or an object with ``.name``)."""
    if not file:
        return gr.skip()
    path = Path(getattr(file, "name", file))
    return path.read_text(encoding="utf-8-sig")


def save_script(text: str, name: str, cfg: UIConfig) -> tuple[str | None, str]:
    """Save the script in ``cfg.scripts_dir``. Returns (path, message)."""
    if not (text or "").strip():
        return None, t("ui.script_not_saved")
    cfg.scripts_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.scripts_dir / f"{_safe_name(name, 'script')}.md"
    path.write_text(text, encoding="utf-8")
    return str(path), t("ui.script_saved", path=display_path(path))


# --------------------------------------------------------------------------- #
# Tab 2: voices
# --------------------------------------------------------------------------- #


def voice_headers() -> list[str]:
    """Column headers of the voices table."""
    return [t("ui.vcol_name"), t("ui.vcol_language"), t("ui.vcol_engine"),
            t("ui.vcol_description"), t("ui.vcol_ref_duration"), t("ui.vcol_xtts_speaker"),
            t("ui.vcol_provider_id"), t("ui.vcol_speed")]


# Minimum widths so the headers are not broken letter by letter.
VOICE_COLUMN_WIDTHS = ["110px", "80px", "100px", "220px", "120px", "150px", "150px", "80px"]


def _wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 1)
    except Exception:
        return None


def voices_table(cfg: UIConfig) -> pd.DataFrame:
    rows = []
    for v in list_voices(cfg.voices_dir):
        dur = _wav_seconds(v.ref_wav) if v.has_ref else None
        rows.append([v.name, v.lang, v.engine, v.description,
                     "" if dur is None else dur, v.xtts_speaker or "", v.provider_voice_id or "",
                     v.speed])
    return pd.DataFrame(rows, columns=voice_headers())


def voice_names(cfg: UIConfig) -> list[str]:
    return [v.name for v in list_voices(cfg.voices_dir)]


def voice_details(name: str | None, cfg: UIConfig) -> tuple[str | None, str]:
    """(path of ref.wav or None, Markdown description) of a voice."""
    if not name:
        return None, t("ui.select_voice")
    try:
        v = get_voice(name, cfg.voices_dir)
    except VoiceError as exc:
        return None, f"❌ {format_error(exc)}"
    parts = [t("ui.voice_summary", name=v.name, lang=v.lang, engine=v.engine, speed=v.speed)]
    if v.description:
        parts.append(v.description)
    if v.xtts_speaker:
        parts.append(t("ui.voice_xtts_speaker", speaker=v.xtts_speaker))
    if v.provider_voice_id:
        parts.append(t("ui.voice_provider_id", id=v.provider_voice_id))
    if v.provider_options:
        opts = ", ".join(f"{k}={val}" for k, val in v.provider_options.items())
        parts.append(t("ui.voice_provider_opts", opts=opts))
    if v.ref_text:
        parts.append(t("ui.voice_transcript", text=v.ref_text))
    elif v.has_ref and v.engine == "f5":
        parts.append(t("ui.voice_no_transcript"))
    return (str(v.ref_wav) if v.has_ref else None), "\n\n".join(parts)


def test_voice(name: str | None, engine_choice: str | None, phrase: str | None, cfg: UIConfig
               ) -> tuple[tuple[int, Any] | None, str]:
    """Synthesize a short sentence with the voice. Returns ((sr, audio), message)."""
    if not name:
        return None, t("ui.select_voice")
    try:
        voice = get_voice(name, cfg.voices_dir)
        text = (phrase or "").strip() or TEST_PHRASES.get(voice.lang, TEST_PHRASES["en"])
        seg = Speech(voice=name, text=text, lang=voice.lang)
        options = AssembleOptions(engine_override=_engine_override(engine_choice),
                                  cache_dir=cfg.cache_dir, allow_external_paths=not cfg.remote)
        started = time.perf_counter()
        with _SYNTH_LOCK:
            audio, sr = synthesize_speech(seg, voices_dir=cfg.voices_dir, options=options)
        return (sr, audio), (f"✅ «{text}» ({audio.size / sr:.1f} s, "
                             f"{time.perf_counter() - started:.1f} s)")
    except Exception as exc:  # noqa: BLE001
        return None, f"❌ {format_error(exc)}"


def create_voice(name: str, audio_path: str | None, transcript: str, lang: str, engine: str,
                 description: str, speed: float, xtts_speaker: str | None, overwrite: bool,
                 cfg: UIConfig, provider_voice_id: str | None = None) -> str:
    """Create a voice; returns a message for the user.

    For cloud engines (elevenlabs, azure, openai...) ``provider_voice_id`` is enough.
    """
    name = (name or "").strip()
    if not name:
        return t("ui.need_name")
    speaker = (xtts_speaker or "").strip() or None
    provider_id = (provider_voice_id or "").strip() or None
    cloud = _is_cloud(engine)
    if cloud:
        if not provider_id:
            return t("ui.need_provider_id", engine=engine)
        speaker = None
    elif not audio_path and not speaker:
        return t("ui.need_audio")
    if not cloud and speaker and not audio_path and engine != "xtts":
        engine = "xtts"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            silence_noisy_warnings()
            voice = add_voice(name, audio_path or None, transcript or "", lang=lang or "es",
                              engine=engine or "f5", description=description or "",
                              xtts_speaker=speaker, speed=float(speed or 1.0),
                              voices_dir=cfg.voices_dir, overwrite=bool(overwrite),
                              provider_voice_id=provider_id if cloud else None)
    except Exception as exc:  # noqa: BLE001
        return f"❌ {format_error(exc)}"
    msg = [t("ui.voice_saved", name=voice.name, path=display_path(voice.path))]
    msg += [f"⚠️ {w.message}" for w in caught]
    return "\n\n".join(msg)


def delete_voice(name: str | None, cfg: UIConfig) -> str:
    if not name:
        return t("ui.select_voice")
    try:
        remove_voice(name, cfg.voices_dir)
    except Exception as exc:  # noqa: BLE001
        return f"❌ {format_error(exc)}"
    return t("ui.voice_deleted", name=name)


def xtts_speakers() -> list[str]:
    """Built-in XTTS speakers (``voices.list_xtts_speakers`` if it exists)."""
    from . import voices as voices_mod

    fn = getattr(voices_mod, "list_xtts_speakers", None)
    if fn is None:
        return []
    try:
        return sorted(str(s) for s in fn())
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- #
# Tab 3: system
# --------------------------------------------------------------------------- #


def _dir_stats(path: Path | None, pattern: str = "*") -> tuple[int, int]:
    if not path or not path.is_dir():
        return 0, 0
    files = [p for p in path.glob(pattern) if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _gpu_status() -> str:
    try:
        import torch  # heavy import, but it does not load any model
    except Exception as exc:  # noqa: BLE001
        return t("ui.torch_missing", exc=exc)
    lines = [f"PyTorch {torch.__version__}"]
    if torch.cuda.is_available():
        lines[0] += t("ui.cuda_ok", version=torch.version.cuda)
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            line = f"GPU {i}: {props.name}, {props.total_memory / 1024**3:.1f} GB"
            try:
                free, total = torch.cuda.mem_get_info(i)
                line += t("ui.gpu_free", free=free / 1024**3)
            except Exception:  # noqa: BLE001
                pass
            lines.append(line)
    else:
        lines[0] += t("ui.cuda_missing")
    return "\n".join(f"- {line}" for line in lines)


def _engine_state(d: dict[str, Any]) -> str:
    if not d.get("importable"):
        return t("ui.state_unavailable")
    if not d.get("configured"):
        return t("ui.state_no_key")
    return t("ui.state_ready")


def _engines_status() -> str:
    try:
        info = engine_info()
    except Exception as exc:  # noqa: BLE001
        return t("ui.engines_info_error", exc=exc)
    lines = []
    for name, d in info.items():
        parts = [d.get("kind", "local"), _engine_state(d)]
        if d.get("kind") == "local" and name != "dummy":
            parts.append(f"GPU: {d.get('device')}" if d.get("cuda") else "CPU")
            parts.append(t("ui.model_loaded") if d.get("loaded") else t("ui.model_not_loaded"))
        if d.get("error") and not d.get("importable"):
            parts.append(str(d["error"]))
        lines.append(f"- `{name}`: {', '.join(parts)}")
    return "\n".join(lines) or t("ui.no_info")


def system_status(cfg: UIConfig) -> str:
    n_cache, size_cache = _dir_stats(cfg.cache_dir, "*.npz")
    n_out, size_out = _dir_stats(cfg.output_dir)
    n_voices = len(list_voices(cfg.voices_dir))
    return "\n".join([
        "### GPU",
        _gpu_status(),
        "",
        t("ui.h_engines"),
        _engines_status(),
        "",
        t("ui.h_paths"),
        t("ui.path_voices", path=display_path(cfg.voices_dir), n=n_voices),
        t("ui.path_cache", path=display_path(cfg.cache_dir) or t("ui.cache_disabled"),
          n=n_cache, size=_mb(size_cache)),
        t("ui.path_output", path=display_path(cfg.output_dir), n=n_out, size=_mb(size_out)),
        t("ui.path_scripts", path=display_path(cfg.scripts_dir)),
    ])


def clear_cache(cfg: UIConfig) -> str:
    if not cfg.cache_dir or not cfg.cache_dir.is_dir():
        return t("ui.cache_empty")
    n = size = 0
    for p in cfg.cache_dir.glob("*.npz"):
        try:
            size += p.stat().st_size
            p.unlink()
            n += 1
        except OSError:
            pass
    return t("ui.cache_cleared", n=n, size=_mb(size))


def open_output_folder(cfg: UIConfig, opener: Callable[[str], Any] | None = None) -> str:
    """Open the output folder in the file manager of the computer running the UI.

    Meant for the desktop app and local use (server and user on the same PC).
    ``opener`` replaces the launcher in tests.
    """
    folder = cfg.output_dir
    if cfg.remote:
        return t("ui.open_remote")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return t("ui.open_mkdir_failed", path=display_path(folder), exc=exc)
    if opener is None:
        import subprocess
        import sys

        if sys.platform == "win32":
            opener = os.startfile  # type: ignore[attr-defined]
        else:
            cmd = "open" if sys.platform == "darwin" else "xdg-open"
            opener = lambda p: subprocess.Popen([cmd, p])  # noqa: E731
    try:
        opener(str(folder))
    except Exception as exc:  # noqa: BLE001 - reported to the user
        return t("ui.open_failed", path=display_path(folder), exc=exc)
    return t("ui.opened", path=display_path(folder))


def output_files(cfg: UIConfig) -> list[str]:
    if not cfg.output_dir.is_dir():
        return []
    files = [p for p in cfg.output_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files]


# --------------------------------------------------------------------------- #
# Tab 4: settings (API keys, licenses and language)
# --------------------------------------------------------------------------- #


def engine_headers() -> list[str]:
    """Column headers of the engines table."""
    return [t("ui.ecol_engine"), t("ui.ecol_type"), t("ui.ecol_license"),
            t("ui.ecol_commercial"), t("ui.ecol_configured"), t("ui.ecol_available"),
            t("ui.ecol_notes")]


ENGINE_COLUMN_WIDTHS = ["100px", "70px", "170px", "120px", "130px", "100px", "360px"]


def _yes_no(value: Any) -> str:
    from .engines import COMMERCIAL_DEPENDS

    if value == COMMERCIAL_DEPENDS:
        return t("common.depends_on_plan")
    return t("common.yes") if value is True else (t("common.no") if value is False else str(value))


def engines_table() -> pd.DataFrame:
    """Engines table with their license and whether they allow commercial use (no torch)."""
    rows = []
    for name, d in engine_info(check_cuda=False).items():
        configured = _yes_no(d.get("configured"))
        if d.get("missing_config"):
            configured = t("ui.missing_config", names=", ".join(d["missing_config"]))
        kind = t("ui.kind_cloud") if d.get("kind") == "cloud" else t("ui.kind_local")
        rows.append([name, kind, d.get("license", ""),
                     _yes_no(d.get("commercial_use")), configured,
                     _yes_no(bool(d.get("importable"))), d.get("license_notes", "")])
    return pd.DataFrame(rows, columns=engine_headers())


def api_key_names() -> list[str]:
    """Variables that can be configured: the known ones and those required by the engines."""
    names = list(config_mod.KNOWN_KEYS)
    for d in engine_info(check_cuda=False).values():
        names += [k for k in d.get("required_config", []) if k not in names]
    return names


def settings_status() -> str:
    """Status of the keys in Markdown (always masked)."""
    lines = [t("ui.env_file", path=display_path(config_mod.env_file_path())), ""]
    for st in config_mod.key_status(api_key_names()):
        if st.is_set:
            where = t("ui.source_env") if st.source == "env" else ".env"
            lines.append(f"- `{st.name}`: ✅ `{st.masked}` ({where})")
        else:
            lines.append(t("ui.key_not_set", name=st.name))
    lines += ["", t("ui.env_priority")]
    return "\n".join(lines)


def save_api_key(name: str | None, value: str | None) -> str:
    """Save a key in ``.env``. Never returns the full value."""
    if not name:
        return t("ui.choose_variable")
    if not (value or "").strip():
        return t("ui.enter_value")
    try:
        config_mod.set_key(name, value or "")
    except config_mod.ConfigError as exc:
        return f"❌ {exc}"
    shown = config_mod.mask(value) if config_mod.is_secret(name) else (value or "").strip()
    msg = t("ui.key_saved", name=name, shown=shown)
    if os.environ.get(name):
        msg += t("ui.key_env_priority")
    return msg


def delete_api_key(name: str | None) -> str:
    """Remove a key from ``.env``."""
    if not name:
        return t("ui.choose_variable")
    try:
        found = config_mod.delete_key(name)
    except config_mod.ConfigError as exc:
        return f"❌ {exc}"
    msg = t("ui.key_deleted", name=name) if found else t("ui.key_absent", name=name)
    if os.environ.get(name):
        msg += t("ui.key_env_still")
    return msg


def language_choices() -> list[tuple[str, str]]:
    """``(native name, code)`` pairs for the language selector."""
    return [(i18n.LANGUAGE_NAMES[code], code) for code in i18n.available_languages()]


def save_ui_language(lang: str | None) -> str:
    """Save the UI language in ``.env`` (applies on the next start). Returns a message."""
    code = i18n.normalize_language(lang)
    if code is None:
        return t("ui.lang_invalid")
    try:
        i18n.save_language(code)
    except (ValueError, OSError) as exc:
        return f"❌ {exc}"
    msg = t("ui.lang_saved", name=i18n.LANGUAGE_NAMES[code])
    env_value = os.environ.get(i18n.ENV_VAR, "").strip()
    if i18n.normalize_language(env_value) not in (None, code):
        msg += t("ui.lang_env_override", env=i18n.ENV_VAR, value=env_value)
    return msg


def _outputs_summary(cfg: UIConfig) -> tuple[str, list[str] | None]:
    files = output_files(cfg)
    return t("ui.outputs_summary", n=len(files), path=display_path(cfg.output_dir)), (files or None)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

APP_NAME = "AudioGeneration"
APP_TAGLINE = "Podcast TTS Studio"
ASSETS_DIR = PROJECT_ROOT / "assets"
ICON_PNG = ASSETS_DIR / "icon.png"
ICON_ICO = ASSETS_DIR / "icon.ico"

CSS = """
#script-editor textarea { font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
                          font-size: 14px; }
#gen-log textarea { font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
                    font-size: 12px; }
.ag-header { display: flex; align-items: center; gap: 14px; padding: 6px 2px 4px; }
.ag-header img { width: 52px; height: 52px; border-radius: 14px;
                 box-shadow: 0 4px 14px rgba(124, 58, 237, .28); }
.ag-header .ag-title { font-size: 1.65rem; font-weight: 750; line-height: 1.1; margin: 0;
                       letter-spacing: -.01em;
                       background: linear-gradient(90deg, #7c3aed, #db2777 60%, #fb7185);
                       -webkit-background-clip: text; background-clip: text; color: transparent; }
.ag-header .ag-sub { margin: 3px 0 0; font-size: .92rem; color: var(--body-text-color-subdued); }
.ag-header .ag-badge { margin-left: auto; align-self: flex-start; font-size: .75rem;
                       padding: 3px 9px; border-radius: 999px;
                       border: 1px solid var(--border-color-primary);
                       color: var(--body-text-color-subdued); white-space: nowrap; }
.dark .ag-header .ag-title { background: linear-gradient(90deg, #c4b5fd, #f9a8d4 60%, #fda4af);
                             -webkit-background-clip: text; background-clip: text; }
"""


def _theme() -> gr.themes.Base:
    """Light/dark theme (follows the system preference) with the icon's colors."""
    return gr.themes.Soft(
        primary_hue="violet", secondary_hue="pink", neutral_hue="slate",
        font=["Segoe UI Variable", "Segoe UI", "system-ui", "sans-serif"],
        font_mono=["Cascadia Code", "Consolas", "ui-monospace", "monospace"],
    ).set(
        button_primary_background_fill="linear-gradient(90deg, *primary_600, *secondary_500)",
        button_primary_background_fill_hover="linear-gradient(90deg, *primary_500, *secondary_400)",
        button_primary_background_fill_dark="linear-gradient(90deg, *primary_600, *secondary_600)",
        button_primary_text_color="white",
        button_primary_text_color_dark="white",
    )


def _icon_data_uri() -> str:
    """The icon embedded as base64 (does not depend on paths served by Gradio)."""
    import base64

    try:
        return "data:image/png;base64," + base64.b64encode(ICON_PNG.read_bytes()).decode("ascii")
    except OSError:
        return ""


def header_html() -> str:
    """App header: icon, name and version."""
    from . import __version__

    uri = _icon_data_uri()
    img = f'<img src="{uri}" alt="">' if uri else ""
    return (
        f'<div class="ag-header">{img}<div>'
        f'<p class="ag-title">{APP_NAME}</p>'
        f'<p class="ag-sub">{APP_TAGLINE} · {t("ui.tagline")}</p></div>'
        f'<span class="ag-badge">v{__version__}</span></div>'
    )


def build_app(cfg: UIConfig | None = None) -> gr.Blocks:
    """Build the Gradio app (it neither loads models nor launches it)."""
    cfg = cfg or UIConfig()
    try:
        initial_script = default_script_path().read_text(encoding="utf-8")
    except OSError:
        initial_script = t("ui.fallback_script")

    with gr.Blocks(title=f"{APP_NAME} — {APP_TAGLINE}", analytics_enabled=False) as app:
        gr.HTML(header_html())

        # ----------------------------------------------------------- Script
        with gr.Tab(t("ui.tab_script")):
            with gr.Row():
                with gr.Column(scale=3):
                    editor = gr.Textbox(value=initial_script, label=t("ui.lbl_script"), lines=24,
                                        max_lines=60, elem_id="script-editor")
                    with gr.Row():
                        load_file = gr.File(label=t("ui.lbl_load_script"),
                                            file_types=[".md", ".txt"], type="filepath",
                                            height=90)
                        with gr.Column():
                            save_name = gr.Textbox(value=t("ui.default_script_name"),
                                                   label=t("ui.lbl_save_name"), max_lines=1)
                            save_btn = gr.Button(t("ui.btn_save_script"))
                    save_msg = gr.Markdown()
                    saved_file = gr.File(label=t("ui.lbl_saved_script"), visible=False)
                with gr.Column(scale=2):
                    engine = gr.Dropdown(engine_choices(), value=ENGINE_AUTO,
                                         label=t("ui.lbl_engine"), info=t("ui.engine_auto_info"))
                    engine_notice = gr.Markdown()
                    out_name = gr.Textbox(value=t("ui.default_episode_name"),
                                          label=t("ui.lbl_output_name"), max_lines=1)
                    with gr.Row():
                        fmt = gr.Radio(["mp3", "wav"], value="mp3", label=t("ui.lbl_format"))
                        bitrate = gr.Dropdown(BITRATES, value="192k", label=t("ui.lbl_bitrate"))
                    normalize = gr.Checkbox(value=True, label=t("ui.lbl_normalize"))
                    with gr.Row():
                        validate_btn = gr.Button(t("ui.btn_validate"))
                        generate_btn = gr.Button(t("ui.btn_generate"), variant="primary")
                    player = gr.Audio(label=t("ui.lbl_result"), type="filepath",
                                      interactive=False)
                    download = gr.File(label=t("ui.lbl_download"), interactive=False)
                    with gr.Row():
                        open_out_btn = gr.Button(t("ui.btn_open_output"), size="sm")
                    open_out_msg = gr.Markdown()
                    log = gr.Textbox(label=t("ui.lbl_log"), lines=10, max_lines=20,
                                     interactive=False, elem_id="gen-log")
            report = gr.Markdown()
            segments = gr.Dataframe(headers=segment_headers(), label=t("ui.lbl_segments"),
                                    interactive=False, wrap=True, max_height=400)
            with gr.Accordion(t("ui.help_title"), open=False):
                gr.Markdown(help_markdown())

            # The API names ("validar", "generar", "probar_voz") are kept for compatibility
            # with existing gradio_client callers.
            validate_btn.click(lambda t_, e: validate_script(t_, e, cfg), [editor, engine],
                               [segments, report], api_name="validar")
            _notice = lambda t_, e: generation_license_notice(t_, e, cfg)  # noqa: E731
            engine.change(_notice, [editor, engine], engine_notice, api_visibility="private")
            editor.blur(_notice, [editor, engine], engine_notice, api_visibility="private")
            validate_btn.click(_notice, [editor, engine], engine_notice, api_visibility="private")

            def _generate(t_, e, n, f, b, norm, progress=gr.Progress()):
                yield from generate_events(t_, e, n, f, b, norm, cfg, progress)

            generate_btn.click(_generate, [editor, engine, out_name, fmt, bitrate, normalize],
                               [player, download, log], api_name="generar")
            load_file.upload(load_script_file, load_file, editor, api_visibility="private")
            open_out_btn.click(lambda: open_output_folder(cfg), None, open_out_msg,
                               api_visibility="private")

            def _save(t_, n):
                path, msg = save_script(t_, n, cfg)
                return msg, gr.update(value=path, visible=path is not None)

            save_btn.click(_save, [editor, save_name], [save_msg, saved_file],
                           api_visibility="private")

        # ----------------------------------------------------------- Voices
        with gr.Tab(t("ui.tab_voices")) as voices_tab:
            voices_df = gr.Dataframe(headers=voice_headers(),
                                     label=t("ui.lbl_voices"), interactive=False, wrap=True,
                                     column_widths=VOICE_COLUMN_WIDTHS)
            with gr.Row():
                refresh_voices = gr.Button(t("ui.btn_refresh"))
            with gr.Row():
                with gr.Column():
                    voice_sel = gr.Dropdown(choices=voice_names(cfg),
                                            label=t("ui.lbl_selected_voice"), value=None)
                    voice_info = gr.Markdown(t("ui.select_voice"))
                    ref_player = gr.Audio(label=t("ui.lbl_ref_clip"), type="filepath",
                                          interactive=False)
                with gr.Column():
                    test_engine = gr.Dropdown(engine_choices(), value=ENGINE_AUTO,
                                              label=t("ui.lbl_test_engine"),
                                              info=t("ui.engine_auto_info"))
                    test_phrase = gr.Textbox(label=t("ui.lbl_test_phrase"), max_lines=2)
                    test_btn = gr.Button(t("ui.btn_test_voice"), variant="primary")
                    test_player = gr.Audio(label=t("ui.lbl_test"), interactive=False)
                    test_msg = gr.Markdown()
                    delete_btn = gr.Button(t("ui.btn_delete_voice"), variant="stop")
                    with gr.Row(visible=False) as confirm_row:
                        confirm_md = gr.Markdown()
                        confirm_yes = gr.Button(t("ui.btn_confirm_delete"), variant="stop")
                        confirm_no = gr.Button(t("ui.btn_cancel"))
                    delete_msg = gr.Markdown()

            with gr.Accordion(t("ui.add_voice"), open=False):
                with gr.Row():
                    with gr.Column():
                        new_name = gr.Textbox(label=t("ui.lbl_new_name"), max_lines=1)
                        new_audio = gr.Audio(label=t("ui.lbl_new_audio"),
                                             sources=["upload", "microphone"], type="filepath")
                        new_text = gr.Textbox(label=t("ui.lbl_new_text"), lines=3)
                    with gr.Column():
                        with gr.Row():
                            new_lang = gr.Dropdown(LANG_CHOICES, value=i18n.get_language(),
                                                   label=t("ui.lbl_language"),
                                                   allow_custom_value=True)
                            new_engine = gr.Dropdown(list(engine_names()), value="f5",
                                                     label=t("ui.lbl_engine"))
                        new_provider_id = gr.Textbox(label=t("ui.lbl_provider_id"), max_lines=1,
                                                     visible=False)
                        new_desc = gr.Textbox(label=t("ui.lbl_description"), max_lines=1)
                        new_speed = gr.Slider(0.5, 1.5, value=1.0, step=0.05,
                                              label=t("ui.lbl_speed"))
                        new_speaker = gr.Dropdown(
                            choices=xtts_speakers(), value=None, allow_custom_value=True,
                            label=t("ui.lbl_speaker"))
                        new_overwrite = gr.Checkbox(label=t("ui.lbl_overwrite"))
                        add_btn = gr.Button(t("ui.btn_save_voice"), variant="primary")
                        add_msg = gr.Markdown()

            def _refresh(selected=None):
                names = voice_names(cfg)
                value = selected if selected in names else None
                return voices_table(cfg), gr.update(choices=names, value=value)

            refresh_voices.click(_refresh, [voice_sel], [voices_df, voice_sel],
                                 api_visibility="private")
            voices_tab.select(_refresh, [voice_sel], [voices_df, voice_sel],
                              api_visibility="private")

            def _select(name):
                path, info = voice_details(name, cfg)
                return path, info, gr.update(visible=False), ""

            voice_sel.change(_select, voice_sel, [ref_player, voice_info, confirm_row, delete_msg],
                             api_visibility="private")
            test_btn.click(lambda n, e, p: test_voice(n, e, p, cfg),
                           [voice_sel, test_engine, test_phrase], [test_player, test_msg],
                           api_name="probar_voz")

            def _ask_delete(name):
                if not name:
                    return gr.update(visible=False), "", t("ui.select_voice")
                return gr.update(visible=True), t("ui.confirm_delete", name=name), ""

            delete_btn.click(_ask_delete, voice_sel, [confirm_row, confirm_md, delete_msg],
                             api_visibility="private")
            confirm_no.click(lambda: (gr.update(visible=False), t("ui.cancelled")), None,
                             [confirm_row, delete_msg], api_visibility="private")

            def _do_delete(name):
                msg = delete_voice(name, cfg)
                df, dd = _refresh(None)
                return gr.update(visible=False), msg, df, dd

            confirm_yes.click(_do_delete, voice_sel, [confirm_row, delete_msg, voices_df, voice_sel],
                              api_visibility="private")

            def _add(name, audio, text, lang, eng, desc, speed, speaker, overwrite, provider_id):
                msg = create_voice(name, audio, text, lang, eng, desc, speed, speaker, overwrite,
                                   cfg, provider_voice_id=provider_id)
                df, dd = _refresh(name.strip() if name else None)
                return msg, df, dd

            add_btn.click(_add, [new_name, new_audio, new_text, new_lang, new_engine, new_desc,
                                 new_speed, new_speaker, new_overwrite, new_provider_id],
                          [add_msg, voices_df, voice_sel], api_visibility="private")

            def _engine_form(eng):
                cloud = _is_cloud(eng)
                return (gr.update(visible=cloud), gr.update(visible=not cloud),
                        gr.update(visible=not cloud), gr.update(visible=not cloud))

            new_engine.change(_engine_form, new_engine,
                              [new_provider_id, new_audio, new_text, new_speaker],
                              api_visibility="private")

        # ----------------------------------------------------------- System
        with gr.Tab(t("ui.tab_system")) as system_tab:
            status = gr.Markdown(t("ui.system_hint"))
            with gr.Row():
                refresh_sys = gr.Button(t("ui.btn_refresh"))
                clear_btn = gr.Button(t("ui.btn_clear_cache"))
                sys_open_out = gr.Button(t("ui.btn_open_output"))
            sys_msg = gr.Markdown()
            sys_open_out.click(lambda: open_output_folder(cfg), None, sys_msg,
                               api_visibility="private")
            out_count = gr.Markdown()
            out_files = gr.File(label=t("ui.lbl_output_files"), file_count="multiple",
                                interactive=False)

            def _sys():
                count, files = _outputs_summary(cfg)
                return system_status(cfg), count, files

            refresh_sys.click(_sys, None, [status, out_count, out_files], api_visibility="private")
            system_tab.select(_sys, None, [status, out_count, out_files], api_visibility="private")

            def _clear():
                msg = clear_cache(cfg)
                return (msg, *_sys())

            clear_btn.click(_clear, None, [sys_msg, status, out_count, out_files],
                            api_visibility="private")

        # ----------------------------------------------------------- Settings
        if cfg.remote:
            # API keys cannot be viewed or changed from other computers.
            with gr.Tab(t("ui.tab_settings")):
                gr.Markdown(t("ui.settings_remote"))
        else:
            _settings_tab(app, cfg)

        # Initial values: computed when the page loads (private events, outside the API).
        app.load(lambda: generation_license_notice(initial_script, ENGINE_AUTO, cfg), None,
                 engine_notice, api_visibility="private")
        app.load(lambda: voices_table(cfg), None, voices_df, api_visibility="private")

    app.podcast_config = cfg  # type: ignore[attr-defined]
    return app


def _settings_tab(app: gr.Blocks, cfg: UIConfig) -> None:
    """Settings tab (API keys, licenses and language). Local mode only."""
    with gr.Tab(t("ui.tab_settings")) as settings_tab:
        gr.Markdown(t("ui.lang_intro"))
        with gr.Row():
            ui_lang = gr.Dropdown(language_choices(),
                                  value=i18n.saved_language() or i18n.get_language(),
                                  label=t("ui.lbl_ui_language"))
            lang_save = gr.Button(t("ui.btn_save_language"))
        lang_msg = gr.Markdown()
        lang_save.click(save_ui_language, ui_lang, lang_msg, api_visibility="private")

        gr.Markdown(t("ui.settings_keys_intro"))
        keys_md = gr.Markdown()
        with gr.Row():
            key_name = gr.Dropdown(api_key_names(), value=None, label=t("ui.lbl_variable"),
                                   allow_custom_value=True)
            key_value = gr.Textbox(label=t("ui.lbl_value"), type="password", max_lines=1,
                                   placeholder=t("ui.ph_value"))
        with gr.Row():
            key_save = gr.Button(t("ui.btn_save_key"), variant="primary")
            key_delete = gr.Button(t("ui.btn_delete_key"), variant="stop")
        key_msg = gr.Markdown()
        gr.Markdown(t("ui.settings_licenses"))
        engines_df = gr.Dataframe(headers=engine_headers(),
                                  label=t("ui.lbl_engines"), interactive=False, wrap=True,
                                  column_widths=ENGINE_COLUMN_WIDTHS)
        refresh_settings = gr.Button(t("ui.btn_refresh"))

        def _save_key(name, value):
            return save_api_key(name, value), "", settings_status(), engines_table()

        def _delete_key(name):
            return delete_api_key(name), settings_status(), engines_table()

        key_save.click(_save_key, [key_name, key_value],
                       [key_msg, key_value, keys_md, engines_df], api_visibility="private")
        key_delete.click(_delete_key, key_name, [key_msg, keys_md, engines_df],
                         api_visibility="private")
        _settings = lambda: (settings_status(), engines_table())  # noqa: E731
        refresh_settings.click(_settings, None, [keys_md, engines_df], api_visibility="private")
        settings_tab.select(_settings, None, [keys_md, engines_df], api_visibility="private")
        app.load(_settings, None, [keys_md, engines_df], api_visibility="private")


AUTH_ENV = "PODCAST_TTS_AUTH"
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class RemoteAuthError(ValueError):
    """The UI is exposed outside this computer without a user and password (or with an
    invalid format)."""


def is_loopback_host(host: str | None) -> bool:
    """``True`` if ``host`` only listens on this computer (127.x, ::1, localhost)."""
    h = (host or "").strip().strip("[]").lower()
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def parse_auth(value: str | None) -> tuple[str, str] | None:
    """``"user:password"`` -> ``(user, password)``; ``None``/empty -> ``None``."""
    if value is None or not value.strip():
        return None
    user, sep, password = value.strip().partition(":")
    if not sep or not user.strip() or not password:
        raise RemoteAuthError(t("ui.auth_bad_format", env=AUTH_ENV))
    return user.strip(), password


def resolve_auth(host: str, share: bool, auth: str | tuple[str, str] | None = None
                 ) -> tuple[bool, tuple[str, str] | None]:
    """Return ``(remote, auth)``. Raises :class:`RemoteAuthError` if auth is needed and missing.

    ``auth`` may be ``"user:password"``, a tuple or ``None`` (``$PODCAST_TTS_AUTH`` is read).
    """
    if isinstance(auth, tuple):
        creds: tuple[str, str] | None = auth
    else:
        creds = parse_auth(auth if auth is not None else os.environ.get(AUTH_ENV))
    remote = bool(share) or not is_loopback_host(host)
    if remote and creds is None:
        why = t("ui.auth_why_share") if share else t("ui.auth_why_host", host=host)
        raise RemoteAuthError(t("ui.auth_required", why=why, env=AUTH_ENV))
    return remote, creds


def launch(app: gr.Blocks, *, host: str = "127.0.0.1", port: int = 7860, share: bool = False,
           inbrowser: bool = False, cfg: UIConfig | None = None,
           prevent_thread_lock: bool = False, quiet: bool = False,
           auth: str | tuple[str, str] | None = None) -> Any:
    """Launch the Gradio server.

    With ``prevent_thread_lock=True`` it returns as soon as the server is listening (used by
    the desktop app, which stops it later with ``app.close()``).

    If ``host`` is not a loopback address or ``share=True``, ``auth`` (or
    ``$PODCAST_TTS_AUTH``) is required and the app must have been built in remote mode
    (``UIConfig(remote=True)``); otherwise :class:`RemoteAuthError` is raised.
    """
    cfg = cfg or getattr(app, "podcast_config", None) or UIConfig()
    remote, creds = resolve_auth(host, share, auth)
    if remote and not cfg.remote:
        raise RemoteAuthError(t("ui.auth_local_app"))
    for d in (cfg.output_dir, cfg.scripts_dir, cfg.voices_dir):
        d.mkdir(parents=True, exist_ok=True)
    return app.queue(default_concurrency_limit=1).launch(
        server_name=host, server_port=port, share=share, inbrowser=inbrowser,
        allowed_paths=[str(cfg.output_dir), str(cfg.voices_dir), str(cfg.scripts_dir),
                       str(PROJECT_ROOT / "examples")],
        theme=_theme(), css=CSS, footer_links=["gradio"],
        favicon_path=str(ICON_PNG) if ICON_PNG.is_file() else None,
        prevent_thread_lock=prevent_thread_lock, quiet=quiet, auth=creds,
    )


def build_arg_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = parser or argparse.ArgumentParser(prog="podcast_tts ui",
                                          description=t("ui.h_description"))
    p.add_argument("--port", type=int, default=7860, help=t("cli.h_port"))
    p.add_argument("--host", default="127.0.0.1", help=t("cli.h_host"))
    p.add_argument("--share", action="store_true", help=t("cli.h_share"))
    p.add_argument("--auth", default=None, metavar=t("cli.mv_user_pass"),
                   help=t("cli.h_auth", env=AUTH_ENV))
    p.add_argument("--inbrowser", action="store_true", help=t("cli.h_inbrowser"))
    p.add_argument("--voices-dir", default=None, help=t("common.voices_dir_short"))
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_from_args(args)


def run_from_args(args: argparse.Namespace) -> int:
    import sys

    try:
        remote, creds = resolve_auth(args.host, args.share, getattr(args, "auth", None))
    except RemoteAuthError as exc:
        print(t("cli.err_generic", exc=exc), file=sys.stderr, flush=True)
        return 2
    kwargs: dict[str, Any] = {"remote": remote}
    if getattr(args, "voices_dir", None):
        kwargs["voices_dir"] = Path(args.voices_dir)
    cfg = UIConfig(**kwargs)
    if remote:
        print(t("ui.remote_mode"), flush=True)
    print(t("ui.launching", host=args.host, port=args.port), flush=True)
    launch(build_app(cfg), host=args.host, port=args.port, share=args.share,
           inbrowser=getattr(args, "inbrowser", False), cfg=cfg, auth=creds)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
