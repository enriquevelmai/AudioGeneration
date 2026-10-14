"""Servidor MCP (Model Context Protocol) de podcast_tts, por stdio.

Expone la herramienta a cualquier asistente de IA compatible con MCP (Claude Desktop,
Claude Code, Cursor, VS Code...) para que pueda escribir un guion, validarlo y generar el
podcast completo en local. Arranque::

    podcast-tts mcp                 # o: python -m podcast_tts mcp   |   podcast-tts-mcp

Requiere el extra ``mcp`` (``uv sync --extra mcp``). Referencia: ``docs/MCP.md``.

Reglas de diseño:

- stdout es SOLO del protocolo JSON-RPC. Al arrancar se duplica el descriptor 1 para el
  transporte y el descriptor 1 del proceso pasa a apuntar a stderr, de modo que cualquier
  ``print`` de torch, f5-tts, gradio, ffmpeg... acaba en stderr. stdin se sustituye por
  ``NUL`` para que ninguna biblioteca pueda consumir mensajes del protocolo con ``input()``.
- La síntesis se ejecuta en un hilo (una a la vez: hay una sola GPU) y envía notificaciones de
  progreso por segmento. Si tarda más que ``wait_seconds`` (45 s por defecto, para no chocar con
  los *timeouts* de los clientes), la herramienta devuelve un ``job_id`` y el trabajo sigue en
  segundo plano; ``get_generation_status`` espera de nuevo y devuelve el resultado.
- Salida en ``<proyecto>/output`` o en ``$PODCAST_TTS_OUTPUT_DIR``. Los nombres de salida se
  validan (sin rutas ni ``..``). Las rutas de música/sfx siguen las reglas de la UI.
"""

import io
import logging
import os
import re
import sys
import threading
import time
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = ["ServerConfig", "build_server", "main", "protect_stdio", "run"]

log = logging.getLogger("podcast_tts.mcp")

SERVER_NAME = "podcast-tts"
WORDS_PER_MINUTE = 150
DEFAULT_WAIT_SECONDS = 45.0
MAX_WAIT_SECONDS = 600.0
MAX_SCRIPT_CHARS = 200_000
MAX_SYNTH_TEXT_CHARS = 5_000
try:  # misma lista que el ensamblador (rutas de música/sfx permitidas)
    from .assembler import AUDIO_EXTENSIONS
except ImportError:  # pragma: no cover
    AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".flac", ".m4a"})
OUTPUT_FORMATS = ("mp3", "wav")
_NAME_RE = re.compile(r"^[\w][\w\-. ]{0,99}$", re.UNICODE)
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


# --------------------------------------------------------------------------- #
# stdio limpio
# --------------------------------------------------------------------------- #


def protect_stdio() -> tuple[io.TextIOWrapper, io.TextIOWrapper]:
    """Reserva stdin/stdout reales para el protocolo y desvía los del proceso.

    Devuelve ``(stdin_protocolo, stdout_protocolo)`` como flujos de texto UTF-8. Después de
    llamarla, el descriptor 1 apunta a stderr (``print`` y subprocesos escriben en stderr) y el
    0 a ``NUL`` (``input()`` recibe EOF).
    """
    sys.stdout.flush()
    proto_out_fd = os.dup(1)
    proto_in_fd = os.dup(0)
    os.dup2(2, 1)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    # Los objetos de Python también: print() -> stderr; input() -> EOF.
    sys.stdout = sys.stderr
    sys.stdin = open(os.devnull, encoding="utf-8")  # noqa: SIM115 - vive todo el proceso
    proto_out = io.TextIOWrapper(os.fdopen(proto_out_fd, "wb", buffering=0), encoding="utf-8",
                                 newline="\n", write_through=True)
    proto_in = io.TextIOWrapper(os.fdopen(proto_in_fd, "rb", buffering=0), encoding="utf-8",
                                errors="replace")
    return proto_in, proto_out


def _setup_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("mcp").setLevel(logging.WARNING)  # sin "Processing request..." por llamada
    warnings.formatwarning = lambda msg, cat, *a, **k: f"Aviso: {msg}\n"
    os.environ.setdefault("PYTHONUTF8", "1")


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #


def _project_root() -> Path:
    from .voices import PROJECT_ROOT

    return PROJECT_ROOT


@dataclass
class ServerConfig:
    """Rutas del servidor (se pueden cambiar en los tests)."""

    output_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("PODCAST_TTS_OUTPUT_DIR") or _project_root() / "output"))
    voices_dir: Path | None = None  # None = default_voices_dir() (respeta PODCAST_TTS_VOICES_DIR)
    scripts_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("PODCAST_TTS_SCRIPTS_DIR") or _project_root() / "guiones"))
    # Igual que la UI: las rutas relativas de música/sfx de un guion pegado se buscan en examples/
    script_base_dir: Path = field(default_factory=lambda: _project_root() / "examples")
    cache_dir: Path | None = None  # None = la caché por defecto (.cache/tts)
    default_wait: float = field(default_factory=lambda: _env_float(
        "PODCAST_TTS_MCP_WAIT", DEFAULT_WAIT_SECONDS))

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir).expanduser().resolve()
        self.scripts_dir = Path(self.scripts_dir).expanduser().resolve()
        self.script_base_dir = Path(self.script_base_dir)
        if self.voices_dir is not None:
            self.voices_dir = Path(self.voices_dir)

    def voices_root(self) -> Path:
        from .voices import default_voices_dir

        return Path(self.voices_dir) if self.voices_dir else default_voices_dir()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


class ToolInputError(ValueError):
    """Argumento inválido de una herramienta (el mensaje se devuelve al modelo)."""


def validate_output_name(name: str | None, fmt: str, default: str = "podcast") -> str:
    """Nombre de fichero seguro (sin rutas ni ``..``), sin extensión. Lanza ToolInputError."""
    raw = (name or "").strip() or default
    if any(sep in raw for sep in ("/", "\\", ":")) or ".." in raw:
        raise ToolInputError(
            f"invalid output_name {raw!r}: give a plain file name without folders, drive "
            "letters or '..' (e.g. 'historia_del_cafe'); files are always written to the "
            "output folder")
    stem = raw
    for ext in OUTPUT_FORMATS:
        if stem.lower().endswith("." + ext):
            stem = stem[: -len(ext) - 1]
    stem = stem.strip(" .")
    if not _NAME_RE.match(stem) or stem.split(".")[0].lower() in _RESERVED:
        raise ToolInputError(
            f"invalid output_name {raw!r}: use letters, numbers, spaces, '_', '-' or '.' "
            "(max 100 characters)")
    return stem


def _unique_path(folder: Path, stem: str, ext: str, overwrite: bool) -> Path:
    path = folder / f"{stem}.{ext}"
    if overwrite or not path.exists():
        return path
    n = 2
    while (folder / f"{stem}-{n}.{ext}").exists():
        n += 1
    return folder / f"{stem}-{n}.{ext}"


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _check_format(fmt: str | None) -> str:
    fmt = (fmt or "mp3").lower().lstrip(".")
    if fmt not in OUTPUT_FORMATS:
        raise ToolInputError(f"unsupported format {fmt!r}: use 'mp3' or 'wav'")
    return fmt


def _check_engine(engine: str | None) -> str | None:
    from .engines import engine_names

    if engine is None or not str(engine).strip() or str(engine).strip().lower() == "auto":
        return None
    name = str(engine).strip().lower()
    if name not in engine_names():
        raise ToolInputError(f"unknown engine {engine!r}; valid: {', '.join(engine_names())}")
    return name


def resolve_media_path(raw: str, base_dir: Path | None) -> Path | None:
    """Mismas reglas que el ensamblador con ``allow_external_paths=False`` (UI remota).

    Solo rutas relativas, sin ``..``, de ficheros de audio, dentro de la carpeta base del
    guion o del proyecto. Devuelve ``None`` si la ruta no se permite o no existe.
    """
    path = Path(raw)
    if path.is_absolute() or path.drive or path.root or ".." in path.parts:
        return None
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    for root in (base_dir, _project_root()):
        if root is None:
            continue
        root = Path(root).resolve()
        cand = (root / path).resolve()
        if cand.is_relative_to(root) and cand.is_file():
            return cand
    return None


def media_errors(script: Any, base_dir: Path | None) -> list[dict[str, Any]]:
    """Errores de las rutas de música/sfx (no permitidas, inexistentes o que no son audio)."""
    from .script_parser import Music, Sfx

    errors: list[dict[str, Any]] = []
    for seg in script.segments:
        if not isinstance(seg, (Music, Sfx)) or (isinstance(seg, Music) and seg.stop):
            continue
        kind = "music" if isinstance(seg, Music) else "sfx"
        path = Path(seg.path)
        if path.is_absolute() or path.drive or path.root or ".." in path.parts:
            errors.append({"line": seg.line, "message":
                           f"[{kind}:{seg.path}] is not allowed: use a path relative to the "
                           "script folder or the project folder, without '..'"})
        elif path.suffix.lower() not in AUDIO_EXTENSIONS:
            errors.append({"line": seg.line, "message":
                           f"[{kind}:{seg.path}] is not an audio file (allowed: "
                           f"{', '.join(sorted(AUDIO_EXTENSIONS))})"})
        elif resolve_media_path(seg.path, base_dir) is None:
            where = f"{base_dir} or " if base_dir else ""
            errors.append({"line": seg.line, "message":
                           f"[{kind}:{seg.path}] file not found in {where}the project folder. "
                           "Remove the tag or use an existing audio file"})
    return errors


def estimate_seconds(script: Any, *, chunk_gap: float = 0.12) -> float:
    """Duración aproximada: ~150 palabras/minuto + pausas (no cuenta los clips de música)."""
    from .script_parser import Pause, Speech

    total = 0.0
    prev = None
    for seg in script.segments:
        if isinstance(seg, Speech):
            words = len(seg.text.split())
            total += words * 60.0 / WORDS_PER_MINUTE / (seg.speed or 1.0)
            if isinstance(prev, Speech):
                total += chunk_gap
        elif isinstance(seg, Pause):
            total += seg.seconds
        prev = seg
    return round(total, 1)


def _fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _preview(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #


def analyze_script(text: str, cfg: ServerConfig, engine: str | None = None,
                   base_dir: Path | None = None) -> dict[str, Any]:
    """Informe de validación de un guion (no sintetiza)."""
    from .engines import EngineError, engine_info
    from .licensing import engines_in_script, license_notice
    from .script_parser import Music, Pause, ScriptParseError, Sfx, Speech, parse_script
    from .voices import VoiceError, get_voice

    if not (text or "").strip():
        return {"valid": False, "errors": [{"line": None, "message": "the script is empty"}]}
    if len(text) > MAX_SCRIPT_CHARS:
        return {"valid": False, "errors": [{"line": None, "message":
                f"the script is too long ({len(text)} characters, max {MAX_SCRIPT_CHARS}); "
                "split it into several episodes"}]}
    try:
        engine = _check_engine(engine)
    except ToolInputError as exc:
        return {"valid": False, "errors": [{"line": None, "message": str(exc)}]}
    try:
        script = parse_script(text)
    except ScriptParseError as exc:
        return {"valid": False,
                "errors": [{"line": exc.line, "message": exc.message}],
                "hint": "Fix the tag on that line (see get_script_format) and validate again."}

    root = cfg.voices_root()
    errors: list[dict[str, Any]] = []
    warnings_: list[str] = []
    voices_used: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in script.voices:
        try:
            v = get_voice(name, root)
        except VoiceError:
            missing.append(name)
            continue
        voices_used.append({"name": v.name, "lang": v.lang,
                            "engine": engine or script.meta.default_engine or v.engine})
    if missing and engine != "dummy":
        first_line = {}
        for seg in script.segments:
            if isinstance(seg, Speech) and seg.voice in missing:
                first_line.setdefault(seg.voice, seg.line)
        for name in missing:
            errors.append({"line": first_line.get(name), "message":
                           f"voice '{name}' does not exist. Use list_voices to see the "
                           "available voices (never invent names) or add one with add_voice"})
    errors += media_errors(script, base_dir)

    engines = engines_in_script(script, root, engine)
    try:
        info = engine_info(check_cuda=False)
    except Exception:  # noqa: BLE001
        info = {}
    for name in engines:
        d = info.get(name)
        if d is None:
            continue
        if not d.get("importable"):
            errors.append({"line": None, "message": f"engine '{name}' is not available: "
                           f"{d.get('error')}"})
        elif not d.get("configured"):
            errors.append({"line": None, "message": f"engine '{name}' is not configured; "
                           f"missing: {', '.join(d.get('missing_config') or [])} "
                           "(podcast-tts config set ...)"})

    speech = [s for s in script.segments if isinstance(s, Speech)]
    for s in speech:
        if len(s.text) > 300:
            warnings_.append(f"line {s.line}: a very long sentence was split by commas/words; "
                             "shorter sentences sound better")
    if script.meta.lang and len({v["lang"] for v in voices_used}) > 1:
        warnings_.append(
            f"front matter 'lang: {script.meta.lang}' forces that language on every voice; "
            "for bilingual scripts remove it and use [voz:name lang=xx] per passage")
    try:
        notice = license_notice(engines)
    except EngineError:
        notice = None

    segments: list[dict[str, Any]] = []
    for seg in script.segments[:300]:
        if isinstance(seg, Speech):
            segments.append({"type": "speech", "voice": seg.voice, "lang": seg.lang,
                             "text": _preview(seg.text), "line": seg.line})
        elif isinstance(seg, Pause):
            segments.append({"type": "pause", "seconds": seg.seconds, "line": seg.line})
        elif isinstance(seg, Music):
            segments.append({"type": "music_stop" if seg.stop else
                             ("background_music" if seg.background else "music"),
                             "path": seg.path, "line": seg.line})
        elif isinstance(seg, Sfx):
            segments.append({"type": "sfx", "path": seg.path, "line": seg.line})

    words = sum(len(s.text.split()) for s in speech)
    seconds = estimate_seconds(script)
    result: dict[str, Any] = {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings_,
        "title": script.meta.title,
        "segment_count": len(script.segments),
        "speech_segment_count": len(speech),
        "word_count": words,
        "estimated_duration_seconds": seconds,
        "estimated_duration": _fmt_duration(seconds),
        "voices_used": voices_used,
        "missing_voices": missing,
        "engines": engines,
        "license_notice": notice,
        "segments": segments,
    }
    if len(script.segments) > 300:
        result["segments_truncated"] = True
    return result


# --------------------------------------------------------------------------- #
# Trabajos de generación
# --------------------------------------------------------------------------- #

_GPU_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    kind: str
    output: Path
    started: float = field(default_factory=time.perf_counter)
    progress: tuple[float, float, str] = (0, 1, "En cola")
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: str | None = None
    finished: float | None = None
    events: list[tuple[float, float, str]] = field(default_factory=list)

    def update(self, i: float, n: float, msg: str) -> None:
        """Registra un paso (lo llama el hilo de síntesis).

        El total es ``n + 1`` (el último paso es exportar) y el valor nunca repite ni baja,
        como exige MCP para las notificaciones de progreso.
        """
        value, total = float(i), float(n) + 1
        if self.events and value <= self.events[-1][0]:
            value = min(self.events[-1][0] + 0.5, total)
        self.progress = (value, total, msg)
        self.events.append(self.progress)

    def finish_step(self, msg: str) -> None:
        total = self.progress[1]
        if not self.events or self.events[-1][0] < total:
            self.progress = (total, total, msg)
            self.events.append(self.progress)


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def _start_job(kind: str, output: Path, work: Any) -> Job:
    """Lanza ``work(job) -> dict`` en un hilo; serializa el acceso a la GPU."""
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, output=output)
    with _JOBS_LOCK:
        _JOBS[job.id] = job
        # Conserva solo los 50 últimos trabajos terminados.
        finished = [j for j in _JOBS.values() if j.done.is_set()]
        for old in sorted(finished, key=lambda j: j.started)[:-50]:
            _JOBS.pop(old.id, None)

    def runner() -> None:
        try:
            with _GPU_LOCK:
                job.update(0, 0, "Preparando (la primera vez carga los modelos: 10-30 s)")
                job.result = work(job)
        except Exception as exc:  # noqa: BLE001 - se devuelve al modelo
            log.exception("Fallo en el trabajo %s", job.id)
            job.error = _error_text(exc)
        finally:
            job.finished = time.perf_counter()
            job.done.set()

    threading.Thread(target=runner, name=f"podcast-tts-{job.id}", daemon=True).start()
    return job


def _error_text(exc: BaseException) -> str:
    from .script_parser import ScriptParseError

    if isinstance(exc, ScriptParseError):
        return f"script error{f' (line {exc.line})' if exc.line else ''}: {exc.message}"
    return f"{type(exc).__name__}: {exc}"


def _audio_info(path: Path) -> float:
    from pydub import AudioSegment

    try:
        return round(len(AudioSegment.from_file(str(path))) / 1000.0, 2)
    except Exception:  # noqa: BLE001
        return 0.0


async def _await_job(job: Job, ctx: Any, wait_seconds: float | None,
                     cfg: ServerConfig, *, replay: bool = True) -> dict[str, Any]:
    import anyio

    wait = cfg.default_wait if wait_seconds is None else float(wait_seconds)
    wait = max(0.0, min(wait, MAX_WAIT_SECONDS))
    deadline = time.monotonic() + wait
    # Una espera nueva (get_generation_status) empieza en el último paso conocido.
    sent = 0 if replay else max(0, len(job.events) - 1)
    while True:
        # Reenvía todos los pasos nuevos (uno por segmento) desde la última espera.
        done = job.done.is_set()
        events = job.events[sent:]
        sent += len(events)
        if ctx is not None:
            for i, n, msg in events:
                try:
                    await ctx.report_progress(i, max(n, 1), msg)
                except Exception:  # noqa: BLE001 - el cliente puede no aceptar progreso
                    break
        if done:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            i, n, msg = job.progress
            return {
                "status": "running",
                "job_id": job.id,
                "progress": f"{i:g}/{n:g}",
                "current_step": msg,
                "elapsed_seconds": round(time.perf_counter() - job.started, 1),
                "output_path": str(job.output),
                "next_step": f"Still generating. Call get_generation_status(job_id='{job.id}') "
                             "to wait for the result (do not start the generation again).",
            }
        await anyio.sleep(min(0.25, remaining))
    if job.error:
        return {"status": "error", "job_id": job.id, "error": job.error}
    return {"status": "done", "job_id": job.id, **(job.result or {})}


def _render_job(job: Job, segments: Any, *, engine: str | None, base_dir: Path | None,
                cfg: ServerConfig, fmt: str, title: str | None,
                notice: str | None) -> dict[str, Any]:
    from .assembler import AssembleOptions, assemble, export_audio

    # Música/sfx con las mismas restricciones que la UI en modo remoto.
    options = AssembleOptions(engine_override=engine, base_dir=base_dir,
                              allow_external_paths=False)
    if cfg.cache_dir is not None:
        options.cache_dir = cfg.cache_dir

    audio = assemble(segments, voices_dir=cfg.voices_root(), options=options,
                     progress=job.update)
    job.finish_step("Exportando el audio")
    tags = {"title": title} if title else None
    path = export_audio(audio, job.output, bitrate="192k", tags=tags)
    elapsed = time.perf_counter() - job.started
    duration = len(audio) / 1000.0
    result: dict[str, Any] = {
        "output_path": str(Path(path).resolve()),
        "format": fmt,
        "duration_seconds": round(duration, 2),
        "duration": _fmt_duration(duration),
        "generation_seconds": round(elapsed, 1),
        "size_bytes": Path(path).stat().st_size,
    }
    if notice:
        result["license_notice"] = notice
    return result


# --------------------------------------------------------------------------- #
# Guía del formato
# --------------------------------------------------------------------------- #

WRITING_GUIDE = """\
# podcast-tts script guide (for the assistant)

You write a Markdown script; podcast-tts turns it into audio with local voice cloning.
Write the spoken text in the language the user asked for (Spanish, English...). Tags and the
front matter keys below work in any language.

## Minimal valid script

```markdown
---
title: La historia del café
---

[voz:ana]
¡Hola y bienvenidos! Hoy viajamos a Etiopía, donde, según la leyenda, empezó todo.

[voz:carlos]
Así es, Ana. Cuenta la historia que un pastor llamado Kaldi vio a sus cabras muy inquietas...

[pausa:1]
[voz:ana]
Y hasta aquí el episodio de hoy. ¡Gracias por escucharnos!
```

- `[voz:NAME]` (or `[voice:NAME]`) switches the speaker until the next `[voz:]`. NAME must be a
  voice returned by `list_voices`; never invent names. Optional attributes:
  `lang=en`, `speed=0.9` (0.25-4, keep 0.9-1.1), `engine=f5|xtts|...`.
- `[pausa:1.5]` (or `[pause:1.5]`) inserts N seconds of silence.
- A blank line starts a new paragraph (short 0.4 s pause).
- Lines starting with `#` or `<!--` are comments (not spoken): use them for section notes.
- Do NOT put `lang:` in the front matter of a bilingual script: each voice already has its
  language (see `list_voices`); use `[voz:ana lang=en]` for a passage in another language.
- Music/sfx (`[musica:file.mp3 fondo vol=0.12]`, `[sfx:ding.wav]`) only with audio files that
  really exist, as paths relative to the project's examples/ folder (or to the script's folder
  for generate_podcast_from_file) or to the project folder; absolute paths and '..' are not
  allowed. If you have no audio files, do not use these tags.

## Podcast structure that sounds good

1. Hook intro (15-30 s): one surprising fact or question, then hosts introduce the topic.
2. 2-4 blocks, each with a clear idea; mark them with `# Block N: ...` comments and
   `[pausa:1]` between blocks; spoken transitions ("Y esto nos lleva a...").
3. Closing: short recap, one memorable takeaway and a goodbye.
- Natural dialogue between hosts: alternate turns of 1-4 sentences, react to each other
  ("¡No me digas!", "Exacto"), ask questions, avoid long monologues and lists.
- Length: about 150 spoken words per minute (3 min ≈ 450 words, 5 min ≈ 750 words).

## Writing for text-to-speech

- Short, complete sentences (< 250 characters each); punctuation sets the rhythm.
- Write numbers, dates, times, units, symbols and abbreviations as words
  ("mil ochocientos cincuenta", "el veinte por ciento", "por ejemplo", "doctor").
- Expand acronyms the way they should be pronounced; say URLs in words.
- No emojis, markdown formatting (**bold**, bullets, links), tables or code in spoken text.
- In Spanish use opening marks `¿` and `¡`.

## Workflow

1. `list_voices` -> pick voices (default: two hosts in the user's language, e.g. ana + carlos
   for Spanish, emma + david for English).
2. Write the script following this guide.
3. `validate_script` -> fix every error (they include the line number) and re-validate.
4. `generate_podcast` -> if it returns status "running", call `get_generation_status` with the
   job_id until status is "done". Report `output_path` and `duration` to the user.

The full tag reference (in Spanish) follows.
"""


def script_format_text() -> str:
    ref = _project_root() / "skill" / "podcast-tts" / "references" / "formato-guion.md"
    try:
        reference = ref.read_text(encoding="utf-8")
    except OSError:
        reference = ("(Referencia completa no disponible en esta instalación: ver "
                     "skill/podcast-tts/references/formato-guion.md en el repositorio.)")
    return WRITING_GUIDE + "\n---\n\n" + reference


# --------------------------------------------------------------------------- #
# Servidor
# --------------------------------------------------------------------------- #

INSTRUCTIONS = """\
podcast-tts generates podcasts and spoken audio LOCALLY (voice cloning with F5-TTS / XTTS v2 on
the user's GPU, or optional cloud engines). Typical request: "make me a podcast about X".
Workflow: list_voices -> get_script_format (once per conversation) -> write the script (research
the topic first if you have web tools) -> validate_script -> generate_podcast (poll
get_generation_status if it returns status 'running') -> tell the user the output_path and
duration, and offer changes. For a single sentence or paragraph use synthesize_text.
Defaults when the user does not say: two voices (ana and carlos for Spanish, emma and david for
English), 3-5 minutes (~150 words per minute), the user's language. The first generation loads
the models (10-30 s); a 5 minute episode takes about 1-2 minutes on an RTX-class GPU.
"""


def build_server(cfg: ServerConfig | None = None) -> Any:
    """Crea el servidor FastMCP con todas las herramientas, el prompt y el recurso."""
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp.types import ToolAnnotations

    cfg = cfg or ServerConfig()
    mcp = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS, log_level="WARNING")
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    writes = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    def fail(exc: BaseException) -> ToolError:
        return ToolError(str(exc) if isinstance(exc, ToolInputError) else _error_text(exc))

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=read_only)
    def list_voices() -> dict[str, Any]:
        """List the voices available for scripts and synthesize_text.

        Returns each voice's `name` (the value to use in `[voz:name]`), `lang` (its main
        language), `engine` (default TTS engine), `description` (gender/style), whether it is a
        `cloud` voice (paid online service) and whether it has a reference clip. Always call this
        before writing a script: only these names are valid, never invent voice names.
        """
        from .engines import EngineError, engine_kind
        from .voices import list_voices as _list

        voices = []
        for v in _list(cfg.voices_root()):
            try:
                cloud = engine_kind(v.engine) == "cloud"
            except EngineError:
                cloud = False
            voices.append({"name": v.name, "lang": v.lang, "engine": v.engine,
                           "description": v.description, "cloud": cloud,
                           "has_reference_clip": v.has_ref,
                           "xtts_speaker": v.xtts_speaker})
        return {"voices_dir": str(cfg.voices_root()), "voices": voices}

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=read_only)
    def list_engines(check_gpu: bool = False) -> dict[str, Any]:
        """List the text-to-speech engines with their license and status.

        For each engine: `kind` (local or cloud), `license`, `commercial_use` (true, false or
        "depends on plan"), `available` (installed), `configured` (API keys present) and
        `missing_config`. Local models f5 and xtts are NON-COMMERCIAL: if the user needs
        commercial use, choose a voice/engine with a commercial license (elevenlabs, azure,
        openai). `dummy` produces tones (for testing timing only). Set check_gpu=true to also
        report whether a CUDA GPU is usable (slower: imports torch).
        """
        from .engines import engine_info

        info = engine_info(check_cuda=bool(check_gpu))
        engines = []
        for name, d in info.items():
            cu = d["commercial_use"]
            engines.append({
                "name": name, "kind": d["kind"], "license": d["license"],
                "license_url": d["license_url"],
                "commercial_use": cu if isinstance(cu, bool) else "depends on plan",
                "available": d["importable"], "configured": d["configured"],
                "ready": bool(d["importable"] and d["configured"]),
                "missing_config": d["missing_config"], "loaded": d["loaded"],
                **({"gpu": d["cuda"], "device": d["device"]} if check_gpu else {}),
                **({"error": d["error"]} if d["error"] and not d["importable"] else {}),
            })
        return {"engines": engines}

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=read_only)
    def get_script_format() -> str:
        """Return the podcast script format and writing guide. Read it before writing a script.

        Explains the Markdown format with tags (`[voz:name]` speaker changes, `[pausa:N]`
        pauses, comments, music), how to structure an engaging podcast (hook intro, blocks,
        transitions, closing, natural dialogue, ~150 words per minute) and how to write text
        that sounds natural with TTS (numbers and abbreviations in words, short sentences, no
        markdown or emojis). Scripts may be written in any language.
        """
        return script_format_text()

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=read_only)
    def validate_script(script: str, engine: str | None = None) -> dict[str, Any]:
        """Check a podcast script WITHOUT generating audio. Always run it before generate_podcast.

        `script` is the full Markdown script text (any language). Returns `valid`, `errors`
        (each with the `line` number and a message: unknown tags, bad attributes, voices that do
        not exist, missing music files, unavailable engines), `warnings`, the voices used,
        `missing_voices`, `estimated_duration` (~150 words/minute plus pauses), word count,
        the engines that will be used with a `license_notice` if they are non-commercial, and
        the parsed `segments`. Fix all errors and validate again until `valid` is true.
        `engine` optionally forces one engine for every voice (same as in generate_podcast).
        """
        return analyze_script(script, cfg, engine, cfg.script_base_dir)

    # ------------------------------------------------------------------ #
    def _prepare(text: str, engine: str | None, base_dir: Path | None) -> tuple[Any, str | None]:
        from .licensing import engines_in_script, license_notice
        from .script_parser import parse_script

        report = analyze_script(text, cfg, engine, base_dir)
        if not report["valid"]:
            msgs = "; ".join(
                (f"line {e['line']}: " if e.get("line") else "") + e["message"]
                for e in report["errors"])
            raise ToolInputError(f"the script is not valid: {msgs}. Fix it (see "
                                 "get_script_format) and run validate_script again")
        script = parse_script(text)
        notice = license_notice(engines_in_script(script, cfg.voices_root(), engine))
        return script, notice

    def _output(output_name: str | None, fmt: str, default: str, overwrite: bool) -> Path:
        stem = validate_output_name(output_name, fmt, default)
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        path = _unique_path(cfg.output_dir, stem, fmt, overwrite)
        if not _inside(path, cfg.output_dir):  # defensa en profundidad
            raise ToolInputError("invalid output_name")
        return path

    def _save_script(text: str, stem: str) -> str | None:
        try:
            cfg.scripts_dir.mkdir(parents=True, exist_ok=True)
            path = cfg.scripts_dir / f"{stem}.md"
            path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            return str(path)
        except OSError as exc:
            log.warning("No se pudo guardar el guion: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=writes)
    async def generate_podcast(
        script: str,
        output_name: str,
        engine: str | None = None,
        format: Literal["mp3", "wav"] = "mp3",
        overwrite: bool = False,
        save_script: bool = True,
        wait_seconds: float | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Generate the complete podcast audio from a script and return the file path.

        - `script`: full Markdown script (validate it first with validate_script).
        - `output_name`: plain file name without folders, e.g. "historia_del_cafe"; the file is
          written to the podcast-tts output folder (extension added from `format`). If the file
          exists a numeric suffix is added unless `overwrite` is true.
        - `engine`: optional, forces one engine for all voices ("f5", "xtts", "dummy" for a
          quick test with tones, or a cloud engine); by default each voice uses its own engine.
        - `format`: "mp3" (default) or "wav".
        - `save_script`: also saves the script as <scripts folder>/<output_name>.md.
        - `wait_seconds`: how long to wait before returning (default 45 s, max 600).
        Sends progress notifications per segment. The first run loads the models (10-30 s);
        a 5-minute episode takes ~1-2 min on a modern NVIDIA GPU (much longer on CPU). If it is
        not finished within `wait_seconds` it returns status "running" with a `job_id`: then
        call get_generation_status(job_id) - do NOT call generate_podcast again. When done it
        returns `output_path` (absolute), `duration`, `generation_seconds` and a
        `license_notice` if a non-commercial engine was used (tell the user).
        """
        try:
            fmt = _check_format(format)
            eng = _check_engine(engine)
            parsed, notice = _prepare(script, eng, cfg.script_base_dir)
            out = _output(output_name, fmt, "podcast", overwrite)
        except Exception as exc:  # noqa: BLE001
            raise fail(exc) from exc
        saved = _save_script(script, out.stem) if save_script else None
        job = _start_job("podcast", out, lambda j: _render_job(
            j, parsed, engine=eng, base_dir=cfg.script_base_dir, cfg=cfg, fmt=fmt,
            title=parsed.meta.title, notice=notice))
        result = await _await_job(job, ctx, wait_seconds, cfg)
        if saved:
            result["script_path"] = saved
        return result

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=writes)
    async def generate_podcast_from_file(
        path: str,
        output_name: str | None = None,
        engine: str | None = None,
        format: Literal["mp3", "wav"] = "mp3",
        overwrite: bool = False,
        wait_seconds: float | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Generate a podcast from a script file (.md or .txt) already on the user's disk.

        `path` is an absolute path (or relative to the podcast-tts project). Relative music/sfx
        paths inside the script are resolved from the script's folder. `output_name` defaults to
        the script's file name. Otherwise identical to generate_podcast (same result, progress
        and `job_id` / get_generation_status behaviour).
        """
        try:
            p = Path(path).expanduser()
            if not p.is_absolute():
                p = (_project_root() / p) if (_project_root() / p).is_file() else p.resolve()
            if p.suffix.lower() not in (".md", ".txt", ".markdown"):
                raise ToolInputError(f"{p} is not a script (.md or .txt)")
            if not p.is_file():
                raise ToolInputError(f"script file not found: {p}")
            text = p.read_text(encoding="utf-8-sig")
            fmt = _check_format(format)
            eng = _check_engine(engine)
            parsed, notice = _prepare(text, eng, p.resolve().parent)
            out = _output(output_name or p.stem, fmt, "podcast", overwrite)
        except Exception as exc:  # noqa: BLE001
            raise fail(exc) from exc
        job = _start_job("podcast", out, lambda j: _render_job(
            j, parsed, engine=eng, base_dir=p.resolve().parent, cfg=cfg, fmt=fmt,
            title=parsed.meta.title, notice=notice))
        result = await _await_job(job, ctx, wait_seconds, cfg)
        result["script_path"] = str(p.resolve())
        return result

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=read_only)
    async def get_generation_status(job_id: str, wait_seconds: float | None = None,
                                    ctx: Context | None = None) -> dict[str, Any]:
        """Wait for (and return) the result of a generation that returned status "running".

        Waits up to `wait_seconds` (default 45, max 600) while sending progress notifications.
        Returns status "running" again (call it again), "done" (with `output_path`,
        `duration`, `generation_seconds`) or "error" (with the message).
        """
        job = _JOBS.get((job_id or "").strip())
        if job is None:
            raise ToolError(f"unknown job_id {job_id!r} (jobs are lost when the server restarts)")
        return await _await_job(job, ctx, wait_seconds, cfg, replay=False)

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=writes)
    async def synthesize_text(
        text: str,
        voice: str,
        lang: str | None = None,
        output_name: str | None = None,
        engine: str | None = None,
        speed: float | None = None,
        format: Literal["mp3", "wav"] = "mp3",
        overwrite: bool = False,
        wait_seconds: float | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Quick text-to-speech of a sentence or paragraph with one voice (no script needed).

        `text` is spoken literally (any language; max 5000 characters; write numbers and
        abbreviations as words). `voice` must be a name from list_voices. `lang` overrides the
        voice's language (e.g. "en"), `speed` 0.5-2.0, `engine` forces an engine. The file goes
        to the output folder as `output_name` (default "tts_<voice>"). Returns `output_path`,
        `duration` and `generation_seconds` (or a `job_id` to poll with get_generation_status).
        """
        from .script_parser import Speech, chunk_text
        from .voices import VoiceError, get_voice

        try:
            fmt = _check_format(format)
            eng = _check_engine(engine)
            body = " ".join((text or "").split())
            if not body:
                raise ToolInputError("text is empty")
            if len(body) > MAX_SYNTH_TEXT_CHARS:
                raise ToolInputError(f"text is too long ({len(body)} characters, max "
                                     f"{MAX_SYNTH_TEXT_CHARS}); use generate_podcast")
            if speed is not None and not 0.5 <= float(speed) <= 2.0:
                raise ToolInputError("speed must be between 0.5 and 2.0")
            if eng != "dummy":
                try:
                    get_voice(voice, cfg.voices_root())
                except VoiceError as exc:
                    raise ToolInputError(f"{exc}. Use list_voices") from exc
            segments = [Speech(voice=voice, text=chunk, lang=lang or None,
                               speed=float(speed) if speed else None)
                        for chunk in chunk_text(body)]
            safe_voice = re.sub(r"[^\w\-]", "_", voice or "voz")
            out = _output(output_name, fmt, f"tts_{safe_voice}", overwrite)
            from .licensing import license_notice
            from .assembler import AssembleOptions, resolve_speech

            engines = {resolve_speech(s, None, cfg.voices_root(),
                                      AssembleOptions(engine_override=eng)).engine
                       for s in segments}
            notice = license_notice(sorted(engines))
        except Exception as exc:  # noqa: BLE001
            raise fail(exc) from exc
        job = _start_job("tts", out, lambda j: _render_job(
            j, segments, engine=eng, base_dir=None, cfg=cfg, fmt=fmt, title=None,
            notice=notice))
        return await _await_job(job, ctx, wait_seconds, cfg)

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=writes)
    def add_voice(
        name: str,
        audio_path: str,
        transcript: str,
        lang: str = "es",
        engine: str = "f5",
        description: str = "",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Clone a new voice from a local audio clip so it can be used in scripts.

        - `name`: new voice name (letters, numbers, '_' or '-'; no spaces).
        - `audio_path`: absolute path to a clean clip of 5-15 s of ONE person speaking, no
          music (wav, mp3, m4a... anything ffmpeg reads; longer clips are cut to 15 s).
        - `transcript`: the EXACT words spoken in the clip (required by f5 for good results).
        - `lang`: main language code ("es", "en", "fr"...); `engine`: "f5" (Spanish/English,
          best quality) or "xtts" (17 languages).
        - `description`: free text, e.g. "woman, warm, Spanish".
        Only clone voices of people who gave their consent. Returns the saved voice.
        """
        from .voices import VoiceError
        from .voices import add_voice as _add

        try:
            src = Path(audio_path).expanduser()
            if not src.is_absolute():
                raise ToolInputError("audio_path must be an absolute path")
            if not src.is_file():
                raise ToolInputError(f"audio file not found: {src}")
            if src.suffix.lower() not in AUDIO_EXTENSIONS | {".mp4", ".webm", ".mkv", ".mov"}:
                raise ToolInputError(f"{src.name} does not look like an audio file")
            eng = _check_engine(engine) or "f5"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                voice = _add(name, src, transcript or "", lang=lang or "es", engine=eng,
                             description=description or "", voices_dir=cfg.voices_root(),
                             overwrite=overwrite)
        except (VoiceError, ToolInputError) as exc:
            raise fail(exc) from exc
        return {"name": voice.name, "lang": voice.lang, "engine": voice.engine,
                "description": voice.description, "path": str(voice.path),
                "warnings": [str(w.message) for w in caught]}

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=read_only)
    def list_outputs(limit: int = 30) -> dict[str, Any]:
        """List the audio files already generated (newest first) in the output folder.

        Returns the absolute folder path and, for each file, `name`, `path`, `size_bytes` and
        `modified` (ISO time). Use it to find a previous episode.
        """
        files = []
        folder = cfg.output_dir
        if folder.is_dir():
            items = [p for p in folder.iterdir()
                     if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
            items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for p in items[: max(1, min(int(limit or 30), 500))]:
                st = p.stat()
                files.append({"name": p.name, "path": str(p), "size_bytes": st.st_size,
                              "modified": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                        time.localtime(st.st_mtime))})
        return {"output_dir": str(folder), "files": files}

    # ------------------------------------------------------------------ #
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def open_output_folder() -> str:
        """Open the output folder in the file explorer of the computer running podcast-tts.

        Only useful when the user is at that computer (local desktop use).
        """
        import subprocess

        folder = cfg.output_dir
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            else:
                cmd = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([cmd, str(folder)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"could not open {folder}: {exc}") from exc
        return f"Opened {folder}"

    # ------------------------------------------------------------------ #
    @mcp.resource("podcast-tts://script-format", name="script-format",
                  description="podcast-tts script format and TTS writing guide",
                  mime_type="text/markdown")
    def script_format_resource() -> str:
        return script_format_text()

    @mcp.prompt(name="podcast", title="Create a podcast",
                description="Create a podcast about {topic} with {voices} lasting ~{minutes} "
                            "min: research, write the script, validate and generate the audio.")
    def podcast(topic: str, voices: str = "", minutes: str = "4", language: str = "") -> str:
        voices_txt = voices.strip() or ("two hosts (default: ana and carlos for Spanish, "
                                        "emma and david for English)")
        lang_txt = language.strip() or "the language the user is writing in"
        try:
            mins = float(str(minutes).replace(",", ".") or 4)
        except ValueError:
            mins = 4.0
        words = int(round(mins * WORDS_PER_MINUTE))
        return f"""Create a podcast about: {topic}

Voices: {voices_txt}. Target length: ~{mins:g} minutes (~{words} spoken words). Language: \
{lang_txt}.

Follow these steps with the podcast-tts tools:
1. Call list_voices and pick existing voices only (never invent names). Call
   get_script_format and follow it.
2. Gather the content: if you have web search tools, research the topic and use accurate,
   current facts; otherwise use your own knowledge and avoid uncertain claims.
3. Write the script: hook intro, 2-4 blocks with spoken transitions, recap and goodbye;
   natural dialogue alternating short turns between the hosts; numbers and abbreviations
   written as words; no markdown, emojis or lists in the spoken text; ~{words} words.
4. Call validate_script and fix every error until it is valid.
5. Call generate_podcast with a short output_name derived from the topic (e.g.
   "historia_del_cafe"). If it returns status "running", call get_generation_status with the
   job_id until it is "done".
6. Reply with the absolute output_path, the duration, the license_notice if any, and offer
   changes (tone, length, voices, sections)."""

    return mcp


# --------------------------------------------------------------------------- #
# Arranque
# --------------------------------------------------------------------------- #


async def _serve(mcp: Any, proto_in: io.TextIOWrapper, proto_out: io.TextIOWrapper) -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async with stdio_server(stdin=anyio.wrap_file(proto_in),
                            stdout=anyio.wrap_file(proto_out)) as (read, write):
        server = mcp._mcp_server  # noqa: SLF001 - igual que FastMCP.run_stdio_async
        await server.run(read, write, server.create_initialization_options())


def run(cfg: ServerConfig | None = None) -> int:
    """Protege stdio y sirve por stdio hasta que el cliente cierre la conexión."""
    import anyio

    proto_in, proto_out = protect_stdio()
    _setup_logging()
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("Error: falta el paquete 'mcp'. Instala el extra: uv sync --extra mcp "
              "(o ejecuta bats\\install_integrations.bat).", file=sys.stderr)
        return 2
    cfg = cfg or ServerConfig()
    log.info("podcast-tts MCP: salida en %s, voces en %s", cfg.output_dir, cfg.voices_root())
    server = build_server(cfg)
    try:
        anyio.run(_serve, server, proto_in, proto_out)
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entrada de ``podcast-tts-mcp`` (equivale a ``podcast-tts mcp``)."""
    from .cli import main as cli_main

    return cli_main(["mcp", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
