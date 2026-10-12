"""Interfaz web local (Gradio) para generar podcasts y gestionar voces.

Lanzar con::

    python -m podcast_tts ui [--port 7860] [--host 127.0.0.1] [--share]

La app arranca sin cargar ningún modelo: F5-TTS / XTTS se cargan de forma
perezosa en la primera síntesis (``engines.get_engine``).

La lógica está en funciones Python normales (``validate_script``,
``run_generation``, ``generate_events``, ``voices_table``...) que reciben un
:class:`UIConfig`, para poder probarlas sin navegador.
"""

from __future__ import annotations

import argparse
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
from .engines import ENGINE_NAMES, EngineError
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
    "ENGINE_AUTO",
    "UIConfig",
    "build_app",
    "clear_cache",
    "delete_voice",
    "format_error",
    "generate_events",
    "main",
    "output_files",
    "run_generation",
    "save_script",
    "system_status",
    "test_voice",
    "validate_script",
    "voices_table",
]

ENGINE_AUTO = "auto (según voz)"
ENGINE_CHOICES = [ENGINE_AUTO, *ENGINE_NAMES]
LANG_CHOICES = ["es", "en", "fr", "de", "it", "pt", "pl", "nl", "ca", "ja", "zh"]
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
EXAMPLE_SCRIPT = PROJECT_ROOT / "examples" / "ejemplo.md"

# Los modelos no son seguros entre hilos: una síntesis cada vez.
_SYNTH_LOCK = threading.Lock()

HELP_MD = """
### Formato del guion

| Etiqueta | Alias | Efecto | Atributos |
|---|---|---|---|
| `[voz:nombre]` | `[voice:nombre]` | Cambia de hablante hasta la siguiente etiqueta de voz | `lang=es\\|en\\|...`, `speed=1.1`, `engine=f5\\|xtts` |
| `[pausa:1.5]` | `[pause:1.5]` | Silencio de N segundos | — |
| `[musica:ruta.mp3]` | `[music:...]`, `[música:...]` | Inserta un clip musical (avanza el tiempo) | `vol=0-1` (1.0), `fade=seg` (0) |
| `[musica:ruta.mp3 fondo]` | `bg`, `background` | Música de fondo en bucle bajo las voces, con *ducking* | `vol=0-1` (0.15), `fade=seg` (1.5) |
| `[musica:stop]` | `fin`, `parar` | Detiene la música de fondo con fundido | `fade=seg` (1.5) |
| `[sfx:ruta.wav]` | — | Efecto puntual superpuesto (no avanza el tiempo) | `vol=0-1` (1.0) |
| `[titulo:...]` | `[title:...]` | Metadato (no se sintetiza) | — |

- *Front matter* opcional al principio: `title`, `lang`, `default_voice`, `engine`, `paragraph_pause`.
- Las líneas que empiezan por `#` o `<!--` son comentarios.
- Una línea vacía separa párrafos (pausa corta automática).
- Rutas de música/sfx relativas a `examples/`, al directorio actual o al proyecto (o absolutas).
"""


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #


@dataclass
class UIConfig:
    """Rutas que usa la UI (se pueden cambiar para tests)."""

    voices_dir: Path = field(default_factory=default_voices_dir)
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    cache_dir: Path | None = field(default_factory=lambda: DEFAULT_CACHE_DIR)
    scripts_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "guiones")
    script_base_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "examples")
    max_chars: int = DEFAULT_MAX_CHARS

    def __post_init__(self) -> None:
        self.voices_dir = Path(self.voices_dir)
        self.output_dir = Path(self.output_dir)
        self.cache_dir = Path(self.cache_dir) if self.cache_dir else None
        self.scripts_dir = Path(self.scripts_dir)
        self.script_base_dir = Path(self.script_base_dir)


def format_error(exc: BaseException) -> str:
    """Mensaje de error legible en castellano."""
    if isinstance(exc, ScriptParseError):
        where = f" (línea {exc.line})" if exc.line else ""
        return f"Error en el guion{where}: {exc.message}"
    if isinstance(exc, AssembleError):
        return f"Error al montar el episodio: {exc}"
    if isinstance(exc, EngineError):
        return f"Error del motor TTS: {exc}"
    if isinstance(exc, VoiceError):
        return f"Error de voz: {exc}"
    if isinstance(exc, NotImplementedError):
        return f"Función no implementada todavía: {exc}"
    if isinstance(exc, FileNotFoundError):
        return f"Fichero no encontrado: {exc.filename or exc}"
    return f"Error inesperado ({type(exc).__name__}): {exc}"


def _engine_override(choice: str | None) -> str | None:
    if not choice or choice == ENGINE_AUTO:
        return None
    return choice


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _safe_name(name: str, default: str = "episodio") -> str:
    name = Path((name or "").strip()).stem or default
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip(" .")
    return name or default


# --------------------------------------------------------------------------- #
# Pestaña 1: guion -> podcast
# --------------------------------------------------------------------------- #

SEGMENT_HEADERS = ["Nº", "Tipo", "Voz", "Idioma", "Texto / detalle", "Línea"]


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
            voz = seg.voice + (f" ({', '.join(extra)})" if extra else "")
            rows.append([i, "Voz", voz, lang, _short(seg.text), seg.line])
        elif isinstance(seg, Pause):
            rows.append([i, "Pausa", "", "", f"{seg.seconds:g} s", seg.line])
        elif isinstance(seg, Music):
            if seg.stop:
                rows.append([i, "Fin música", "", "", f"fade={seg.fade:g} s", seg.line])
            else:
                kind = "Música de fondo" if seg.background else "Música"
                rows.append([i, kind, "", "", f"{seg.path} (vol={seg.volume:g})", seg.line])
        elif isinstance(seg, Sfx):
            rows.append([i, "Efecto", "", "", f"{seg.path} (vol={seg.volume:g})", seg.line])
    return pd.DataFrame(rows, columns=SEGMENT_HEADERS)


def validate_script(text: str, engine_choice: str | None, cfg: UIConfig
                    ) -> tuple[pd.DataFrame, str]:
    """Parsea el guion. Devuelve (tabla de segmentos, informe Markdown)."""
    empty = pd.DataFrame([], columns=SEGMENT_HEADERS)
    if not (text or "").strip():
        return empty, "⚠️ El guion está vacío."
    try:
        script = parse_script(text, max_chars=cfg.max_chars)
    except ScriptParseError as exc:
        return empty, f"❌ {format_error(exc)}"
    override = _engine_override(engine_choice)
    n_speech = sum(isinstance(s, Speech) for s in script.segments)
    chars = sum(len(s.text) for s in script.segments if isinstance(s, Speech))
    lines = [
        f"✅ Guion válido: **{len(script.segments)}** segmentos, **{n_speech}** frases, "
        f"{chars} caracteres.",
    ]
    if script.meta.title:
        lines.append(f"Título: *{script.meta.title}*")
    lines.append("")
    lines.append("**Voces usadas:**")
    missing = []
    for name in script.voices:
        try:
            voice = get_voice(name, cfg.voices_dir)
        except VoiceError:
            missing.append(name)
            if override == "dummy":
                lines.append(f"- `{name}`: no existe (con el motor *dummy* no importa)")
            else:
                lines.append(f"- ⚠️ `{name}`: **NO EXISTE** en {cfg.voices_dir}")
            continue
        engine = override or script.meta.default_engine or voice.engine
        src = "ref.wav" if voice.has_ref else (
            f"speaker XTTS '{voice.xtts_speaker}'" if voice.xtts_speaker else "⚠️ sin ref.wav")
        lines.append(f"- `{name}`: idioma {voice.lang}, motor {engine}, {src}")
    if not script.voices:
        lines.append("- (ninguna)")
    if missing and override != "dummy":
        lines.append("")
        lines.append(
            f"⚠️ Faltan {len(missing)} voz/voces: créalas en la pestaña **Voces** "
            "o elige el motor *dummy* para probar tiempos."
        )
    return _segments_frame(script, cfg), "\n".join(lines)


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
    """Genera el episodio de forma síncrona. Devuelve (ruta, resumen). Lanza excepciones."""
    if not (text or "").strip():
        raise AssembleError("el guion está vacío")
    fmt = (fmt or "mp3").lower().lstrip(".")
    if fmt not in ("mp3", "wav"):
        raise AssembleError(f"formato no soportado: {fmt}")
    started = time.perf_counter()
    script = parse_script(text, max_chars=cfg.max_chars)
    options = AssembleOptions(
        engine_override=_engine_override(engine_choice),
        target_lufs=-16.0 if normalize else None,
        cache_dir=cfg.cache_dir,
        base_dir=cfg.script_base_dir,
    )
    output = cfg.output_dir / f"{_safe_name(out_name)}.{fmt}"
    with _SYNTH_LOCK:
        audio = assemble(script, voices_dir=cfg.voices_dir, options=options, progress=progress)
    tags = {"title": script.meta.title} if script.meta.title else None
    path = export_audio(audio, output, bitrate=bitrate or "192k", tags=tags)
    elapsed = time.perf_counter() - started
    summary = (f"Listo: {path} — duración {len(audio) / 1000:.1f} s, "
               f"generado en {elapsed:.1f} s")
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
    """Generador para la UI: ejecuta :func:`run_generation` en un hilo y va
    emitiendo ``(audio, fichero, log)``. Los errores se muestran en el log."""
    events: "queue.Queue[tuple]" = queue.Queue()
    result: dict[str, Any] = {}

    def callback(i: int, n: int, msg: str) -> None:
        events.put(("p", i, n, msg))

    def worker() -> None:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result["value"] = run_generation(text, engine_choice, out_name, fmt, bitrate,
                                                 normalize, cfg, callback)
            result["warnings"] = [str(w.message) for w in caught]
        except BaseException as exc:  # noqa: BLE001 - se muestra al usuario
            result["error"] = exc
        finally:
            events.put(("done",))

    log = [f"Motor: {engine_choice or ENGINE_AUTO}. "
           "La primera síntesis con F5/XTTS carga el modelo (puede tardar un poco)."]
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
        while True:  # agrupa los eventos pendientes para no saturar la UI
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
                except Exception:  # fuera de un evento de Gradio
                    pass
        if not done:
            yield skip, skip, "\n".join(log)
    thread.join()
    for w in result.get("warnings", []):
        log.append(f"Aviso: {w}")
    if "error" in result:
        log.append(f"❌ {format_error(result['error'])}")
        yield None, None, "\n".join(log)
        return
    path, summary = result["value"]
    log.append(f"✅ {summary}")
    yield str(path), str(path), "\n".join(log)


def load_script_file(file: Any) -> str:
    """Lee un .md subido (ruta o objeto con ``.name``)."""
    if not file:
        return gr.skip()
    path = Path(getattr(file, "name", file))
    return path.read_text(encoding="utf-8-sig")


def save_script(text: str, name: str, cfg: UIConfig) -> tuple[str | None, str]:
    """Guarda el guion en ``cfg.scripts_dir``. Devuelve (ruta, mensaje)."""
    if not (text or "").strip():
        return None, "⚠️ El guion está vacío: no se guarda nada."
    cfg.scripts_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.scripts_dir / f"{_safe_name(name, 'guion')}.md"
    path.write_text(text, encoding="utf-8")
    return str(path), f"💾 Guion guardado en `{path}`"


# --------------------------------------------------------------------------- #
# Pestaña 2: voces
# --------------------------------------------------------------------------- #

VOICE_HEADERS = ["Nombre", "Idioma", "Motor", "Descripción", "Duración ref (s)", "Speaker XTTS",
                 "Speed"]


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
                     "" if dur is None else dur, v.xtts_speaker or "", v.speed])
    return pd.DataFrame(rows, columns=VOICE_HEADERS)


def voice_names(cfg: UIConfig) -> list[str]:
    return [v.name for v in list_voices(cfg.voices_dir)]


def voice_details(name: str | None, cfg: UIConfig) -> tuple[str | None, str]:
    """(ruta de ref.wav o None, descripción Markdown) de una voz."""
    if not name:
        return None, "Selecciona una voz."
    try:
        v = get_voice(name, cfg.voices_dir)
    except VoiceError as exc:
        return None, f"❌ {format_error(exc)}"
    parts = [f"**{v.name}** — idioma `{v.lang}`, motor `{v.engine}`, speed {v.speed:g}"]
    if v.description:
        parts.append(v.description)
    if v.xtts_speaker:
        parts.append(f"Speaker integrado de XTTS: `{v.xtts_speaker}`")
    if v.ref_text:
        parts.append(f"Transcripción: *{v.ref_text}*")
    elif v.has_ref:
        parts.append("⚠️ Sin transcripción (ref.txt): F5-TTS la necesita.")
    return (str(v.ref_wav) if v.has_ref else None), "\n\n".join(parts)


def test_voice(name: str | None, engine_choice: str | None, phrase: str | None, cfg: UIConfig
               ) -> tuple[tuple[int, Any] | None, str]:
    """Sintetiza una frase corta con la voz. Devuelve ((sr, audio), mensaje)."""
    if not name:
        return None, "Selecciona una voz."
    try:
        voice = get_voice(name, cfg.voices_dir)
        text = (phrase or "").strip() or TEST_PHRASES.get(voice.lang, TEST_PHRASES["en"])
        seg = Speech(voice=name, text=text, lang=voice.lang)
        options = AssembleOptions(engine_override=_engine_override(engine_choice),
                                  cache_dir=cfg.cache_dir)
        started = time.perf_counter()
        with _SYNTH_LOCK:
            audio, sr = synthesize_speech(seg, voices_dir=cfg.voices_dir, options=options)
        return (sr, audio), (f"✅ «{text}» ({audio.size / sr:.1f} s, "
                             f"{time.perf_counter() - started:.1f} s)")
    except Exception as exc:  # noqa: BLE001
        return None, f"❌ {format_error(exc)}"


def create_voice(name: str, audio_path: str | None, transcript: str, lang: str, engine: str,
                 description: str, speed: float, xtts_speaker: str | None, overwrite: bool,
                 cfg: UIConfig) -> str:
    """Crea una voz; devuelve un mensaje para el usuario."""
    name = (name or "").strip()
    if not name:
        return "⚠️ Escribe un nombre para la voz."
    speaker = (xtts_speaker or "").strip() or None
    if not audio_path and not speaker:
        return "⚠️ Sube o graba un audio de referencia, o elige un speaker integrado de XTTS."
    if speaker and not audio_path and engine != "xtts":
        engine = "xtts"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            voice = add_voice(name, audio_path or None, transcript or "", lang=lang or "es",
                              engine=engine or "f5", description=description or "",
                              xtts_speaker=speaker, speed=float(speed or 1.0),
                              voices_dir=cfg.voices_dir, overwrite=bool(overwrite))
    except Exception as exc:  # noqa: BLE001
        return f"❌ {format_error(exc)}"
    msg = [f"✅ Voz '{voice.name}' guardada en `{voice.path}`"]
    msg += [f"⚠️ {w.message}" for w in caught]
    return "\n\n".join(msg)


def delete_voice(name: str | None, cfg: UIConfig) -> str:
    if not name:
        return "Selecciona una voz."
    try:
        remove_voice(name, cfg.voices_dir)
    except Exception as exc:  # noqa: BLE001
        return f"❌ {format_error(exc)}"
    return f"🗑️ Voz '{name}' eliminada."


def xtts_speakers() -> list[str]:
    """Speakers integrados de XTTS (``voices.list_xtts_speakers`` si existe)."""
    from . import voices as voices_mod

    fn = getattr(voices_mod, "list_xtts_speakers", None)
    if fn is None:
        return []
    try:
        return sorted(str(s) for s in fn())
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- #
# Pestaña 3: sistema
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
        import torch  # import pesado pero no carga modelos
    except Exception as exc:  # noqa: BLE001
        return f"PyTorch no disponible: {exc}"
    lines = [f"PyTorch {torch.__version__}"]
    if torch.cuda.is_available():
        lines[0] += f" — CUDA {torch.version.cuda} disponible ✅"
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            line = f"GPU {i}: {props.name}, {props.total_memory / 1024**3:.1f} GB"
            try:
                free, total = torch.cuda.mem_get_info(i)
                line += f" ({free / 1024**3:.1f} GB libres)"
            except Exception:  # noqa: BLE001
                pass
            lines.append(line)
    else:
        lines[0] += " — CUDA NO disponible ⚠️ (la síntesis irá por CPU, muy lenta)"
    return "\n".join(f"- {line}" for line in lines)


def _engines_status() -> str:
    from . import engines as engines_mod

    fn = getattr(engines_mod, "engine_info", None)
    if fn is None:
        return "\n".join(f"- `{n}`" for n in ENGINE_NAMES) + "\n\n(sin `engine_info()`: solo nombres)"
    try:
        info = fn()
    except Exception as exc:  # noqa: BLE001
        return f"No se pudo obtener la información de los motores: {exc}"
    lines = []
    if isinstance(info, dict):
        for name, data in info.items():
            if isinstance(data, dict):
                detail = ", ".join(f"{k}: {v}" for k, v in data.items())
            else:
                detail = str(data)
            lines.append(f"- `{name}`: {detail}")
    elif isinstance(info, (list, tuple)):
        for item in info:
            if isinstance(item, dict):
                name = item.get("name", "?")
                detail = ", ".join(f"{k}: {v}" for k, v in item.items() if k != "name")
                lines.append(f"- `{name}`: {detail}")
            else:
                lines.append(f"- {item}")
    else:
        lines.append(str(info))
    return "\n".join(lines) or "(sin información)"


def system_status(cfg: UIConfig) -> str:
    n_cache, size_cache = _dir_stats(cfg.cache_dir, "*.npz")
    n_out, size_out = _dir_stats(cfg.output_dir)
    n_voices = len(list_voices(cfg.voices_dir))
    return "\n".join([
        "### GPU",
        _gpu_status(),
        "",
        "### Motores",
        _engines_status(),
        "",
        "### Rutas",
        f"- Voces: `{cfg.voices_dir}` ({n_voices} voces)",
        f"- Caché de síntesis: `{cfg.cache_dir or '(desactivada)'}` "
        f"({n_cache} frases, {_mb(size_cache)})",
        f"- Salida: `{cfg.output_dir}` ({n_out} ficheros, {_mb(size_out)})",
        f"- Guiones guardados: `{cfg.scripts_dir}`",
    ])


def clear_cache(cfg: UIConfig) -> str:
    if not cfg.cache_dir or not cfg.cache_dir.is_dir():
        return "La caché está vacía."
    n = size = 0
    for p in cfg.cache_dir.glob("*.npz"):
        try:
            size += p.stat().st_size
            p.unlink()
            n += 1
        except OSError:
            pass
    return f"🧹 Caché vaciada: {n} frases ({_mb(size)})."


def output_files(cfg: UIConfig) -> list[str]:
    if not cfg.output_dir.is_dir():
        return []
    files = [p for p in cfg.output_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files]


def _outputs_summary(cfg: UIConfig) -> tuple[str, list[str] | None]:
    files = output_files(cfg)
    return f"**{len(files)}** ficheros en `{cfg.output_dir}`", (files or None)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

CSS = """
#script-editor textarea { font-family: ui-monospace, Consolas, monospace; font-size: 14px; }
#gen-log textarea { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
"""


def _theme() -> gr.themes.Base:
    return gr.themes.Soft(primary_hue="indigo", neutral_hue="slate")


def build_app(cfg: UIConfig | None = None) -> gr.Blocks:
    """Construye la app Gradio (no carga modelos ni la lanza)."""
    cfg = cfg or UIConfig()
    try:
        initial_script = EXAMPLE_SCRIPT.read_text(encoding="utf-8")
    except OSError:
        initial_script = "[voz:ana] Hola y bienvenidos.\n"

    with gr.Blocks(title="Podcast TTS", analytics_enabled=False) as app:
        gr.Markdown("# 🎙️ Podcast TTS\nGenera podcasts en local a partir de un guion Markdown "
                    "con voces clonadas (F5-TTS / XTTS v2).")

        # ----------------------------------------------------------- Guion
        with gr.Tab("Guion → Podcast"):
            with gr.Row():
                with gr.Column(scale=3):
                    editor = gr.Textbox(value=initial_script, label="Guion (Markdown)", lines=24,
                                        max_lines=60, elem_id="script-editor")
                    with gr.Row():
                        load_file = gr.File(label="Cargar guion (.md)", file_types=[".md", ".txt"],
                                            type="filepath", height=90)
                        with gr.Column():
                            save_name = gr.Textbox(value="mi_guion", label="Nombre al guardar",
                                                   max_lines=1)
                            save_btn = gr.Button("💾 Guardar guion")
                    save_msg = gr.Markdown()
                    saved_file = gr.File(label="Guion guardado", visible=False)
                with gr.Column(scale=2):
                    engine = gr.Dropdown(ENGINE_CHOICES, value=ENGINE_AUTO, label="Motor")
                    out_name = gr.Textbox(value="episodio", label="Nombre del fichero de salida",
                                          max_lines=1)
                    with gr.Row():
                        fmt = gr.Radio(["mp3", "wav"], value="mp3", label="Formato")
                        bitrate = gr.Dropdown(BITRATES, value="192k", label="Bitrate (mp3)")
                    normalize = gr.Checkbox(value=True, label="Normalizar sonoridad (-16 LUFS)")
                    with gr.Row():
                        validate_btn = gr.Button("🔍 Validar")
                        generate_btn = gr.Button("▶️ Generar", variant="primary")
                    player = gr.Audio(label="Resultado", type="filepath", interactive=False)
                    download = gr.File(label="Descargar", interactive=False)
                    log = gr.Textbox(label="Log", lines=10, max_lines=20, interactive=False,
                                     elem_id="gen-log")
            report = gr.Markdown()
            segments = gr.Dataframe(headers=SEGMENT_HEADERS, label="Segmentos", interactive=False,
                                    wrap=True, max_height=400)
            with gr.Accordion("Ayuda: etiquetas del formato", open=False):
                gr.Markdown(HELP_MD)

            validate_btn.click(lambda t, e: validate_script(t, e, cfg), [editor, engine],
                               [segments, report], api_name="validar")

            def _generate(t, e, n, f, b, norm, progress=gr.Progress()):
                yield from generate_events(t, e, n, f, b, norm, cfg, progress)

            generate_btn.click(_generate, [editor, engine, out_name, fmt, bitrate, normalize],
                               [player, download, log], api_name="generar")
            load_file.upload(load_script_file, load_file, editor)

            def _save(t, n):
                path, msg = save_script(t, n, cfg)
                return msg, gr.update(value=path, visible=path is not None)

            save_btn.click(_save, [editor, save_name], [save_msg, saved_file])

        # ----------------------------------------------------------- Voces
        with gr.Tab("Voces") as voices_tab:
            voices_df = gr.Dataframe(value=lambda: voices_table(cfg), headers=VOICE_HEADERS,
                                     label="Voces disponibles", interactive=False, wrap=True)
            with gr.Row():
                refresh_voices = gr.Button("🔄 Actualizar")
            with gr.Row():
                with gr.Column():
                    voice_sel = gr.Dropdown(choices=voice_names(cfg), label="Voz seleccionada",
                                            value=None)
                    voice_info = gr.Markdown("Selecciona una voz.")
                    ref_player = gr.Audio(label="Clip de referencia (ref.wav)", type="filepath",
                                          interactive=False)
                with gr.Column():
                    test_engine = gr.Dropdown(ENGINE_CHOICES, value=ENGINE_AUTO,
                                              label="Motor para la prueba")
                    test_phrase = gr.Textbox(label="Frase de prueba (vacío = frase en su idioma)",
                                             max_lines=2)
                    test_btn = gr.Button("🗣️ Probar voz", variant="primary")
                    test_player = gr.Audio(label="Prueba", interactive=False)
                    test_msg = gr.Markdown()
                    delete_btn = gr.Button("🗑️ Eliminar voz", variant="stop")
                    with gr.Row(visible=False) as confirm_row:
                        confirm_md = gr.Markdown()
                        confirm_yes = gr.Button("Sí, eliminar", variant="stop")
                        confirm_no = gr.Button("Cancelar")
                    delete_msg = gr.Markdown()

            with gr.Accordion("➕ Añadir voz", open=False):
                with gr.Row():
                    with gr.Column():
                        new_name = gr.Textbox(label="Nombre (letras, números, _ o -)", max_lines=1)
                        new_audio = gr.Audio(label="Audio de referencia (5-15 s, sin música)",
                                             sources=["upload", "microphone"], type="filepath")
                        new_text = gr.Textbox(label="Transcripción exacta del clip (necesaria "
                                                    "para F5)", lines=3)
                    with gr.Column():
                        with gr.Row():
                            new_lang = gr.Dropdown(LANG_CHOICES, value="es", label="Idioma",
                                                   allow_custom_value=True)
                            new_engine = gr.Dropdown(list(ENGINE_NAMES), value="f5", label="Motor")
                        new_desc = gr.Textbox(label="Descripción", max_lines=1)
                        new_speed = gr.Slider(0.5, 1.5, value=1.0, step=0.05, label="Velocidad")
                        new_speaker = gr.Dropdown(
                            choices=xtts_speakers(), value=None, allow_custom_value=True,
                            label="…o speaker integrado de XTTS (en vez de clonar; deja el "
                                  "audio vacío)")
                        new_overwrite = gr.Checkbox(label="Sobrescribir si existe")
                        add_btn = gr.Button("Guardar voz", variant="primary")
                        add_msg = gr.Markdown()

            def _refresh(selected=None):
                names = voice_names(cfg)
                value = selected if selected in names else None
                return voices_table(cfg), gr.update(choices=names, value=value)

            refresh_voices.click(_refresh, [voice_sel], [voices_df, voice_sel])
            voices_tab.select(_refresh, [voice_sel], [voices_df, voice_sel])

            def _select(name):
                path, info = voice_details(name, cfg)
                return path, info, gr.update(visible=False), ""

            voice_sel.change(_select, voice_sel, [ref_player, voice_info, confirm_row, delete_msg])
            test_btn.click(lambda n, e, p: test_voice(n, e, p, cfg),
                           [voice_sel, test_engine, test_phrase], [test_player, test_msg],
                           api_name="probar_voz")

            def _ask_delete(name):
                if not name:
                    return gr.update(visible=False), "", "Selecciona una voz."
                return (gr.update(visible=True),
                        f"¿Seguro que quieres eliminar **{name}**? No se puede deshacer.", "")

            delete_btn.click(_ask_delete, voice_sel, [confirm_row, confirm_md, delete_msg])
            confirm_no.click(lambda: (gr.update(visible=False), "Cancelado."), None,
                             [confirm_row, delete_msg])

            def _do_delete(name):
                msg = delete_voice(name, cfg)
                df, dd = _refresh(None)
                return gr.update(visible=False), msg, df, dd

            confirm_yes.click(_do_delete, voice_sel, [confirm_row, delete_msg, voices_df, voice_sel])

            def _add(name, audio, text, lang, eng, desc, speed, speaker, overwrite):
                msg = create_voice(name, audio, text, lang, eng, desc, speed, speaker, overwrite,
                                   cfg)
                df, dd = _refresh(name.strip() if name else None)
                return msg, df, dd

            add_btn.click(_add, [new_name, new_audio, new_text, new_lang, new_engine, new_desc,
                                 new_speed, new_speaker, new_overwrite],
                          [add_msg, voices_df, voice_sel])

        # ----------------------------------------------------------- Sistema
        with gr.Tab("Sistema") as system_tab:
            status = gr.Markdown("Pulsa **Actualizar** para ver el estado del sistema.")
            with gr.Row():
                refresh_sys = gr.Button("🔄 Actualizar")
                clear_btn = gr.Button("🧹 Vaciar caché de síntesis")
            sys_msg = gr.Markdown()
            out_count = gr.Markdown()
            out_files = gr.File(label="Ficheros en output/", file_count="multiple",
                                interactive=False)

            def _sys():
                count, files = _outputs_summary(cfg)
                return system_status(cfg), count, files

            refresh_sys.click(_sys, None, [status, out_count, out_files])
            system_tab.select(_sys, None, [status, out_count, out_files])

            def _clear():
                msg = clear_cache(cfg)
                return (msg, *_sys())

            clear_btn.click(_clear, None, [sys_msg, status, out_count, out_files])

    app.podcast_config = cfg  # type: ignore[attr-defined]
    return app


def launch(app: gr.Blocks, *, host: str = "127.0.0.1", port: int = 7860, share: bool = False,
           inbrowser: bool = False, cfg: UIConfig | None = None) -> None:
    cfg = cfg or getattr(app, "podcast_config", None) or UIConfig()
    for d in (cfg.output_dir, cfg.scripts_dir, cfg.voices_dir):
        d.mkdir(parents=True, exist_ok=True)
    app.queue(default_concurrency_limit=1).launch(
        server_name=host, server_port=port, share=share, inbrowser=inbrowser,
        allowed_paths=[str(cfg.output_dir), str(cfg.voices_dir), str(cfg.scripts_dir),
                       str(PROJECT_ROOT / "examples")],
        theme=_theme(), css=CSS, footer_links=["gradio"],
    )


def build_arg_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = parser or argparse.ArgumentParser(prog="podcast_tts ui",
                                          description="Lanza la interfaz web local (Gradio).")
    p.add_argument("--port", type=int, default=7860, help="puerto (por defecto 7860)")
    p.add_argument("--host", default="127.0.0.1", help="interfaz de red (por defecto 127.0.0.1)")
    p.add_argument("--share", action="store_true", help="crea un enlace público temporal de Gradio")
    p.add_argument("--inbrowser", action="store_true", help="abre el navegador al arrancar")
    p.add_argument("--voices-dir", default=None, help="directorio de voces")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_from_args(args)


def run_from_args(args: argparse.Namespace) -> int:
    cfg = UIConfig(voices_dir=Path(args.voices_dir)) if getattr(args, "voices_dir", None) \
        else UIConfig()
    print(f"Lanzando la UI en http://{args.host}:{args.port} (Ctrl+C para salir)", flush=True)
    launch(build_app(cfg), host=args.host, port=args.port, share=args.share,
           inbrowser=getattr(args, "inbrowser", False), cfg=cfg)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
