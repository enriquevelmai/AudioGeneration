"""Interfaz de línea de comandos.

Ejemplos::

    python -m podcast_tts generate guion.md -o output/episodio.mp3 [--engine dummy]
    python -m podcast_tts parse guion.md
    python -m podcast_tts voices list
    python -m podcast_tts voices add ana clip.wav --text "Transcripción del clip" --lang es
    python -m podcast_tts voices remove ana
    python -m podcast_tts ui [--port 7860] [--host 127.0.0.1] [--share]
    python -m podcast_tts models list|status [--json]
    python -m podcast_tts models download [f5-base|f5-spanish|vocos|xtts|whisper|all]
    python -m podcast_tts models update [nombre|all]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Sequence

from . import __version__
from .engines import ENGINE_NAMES
from .script_parser import DEFAULT_MAX_CHARS, ScriptParseError, parse_file

__all__ = ["build_parser", "main"]


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def _setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    warnings.formatwarning = lambda msg, cat, *a, **k: f"Aviso: {msg}\n"


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #


def _cmd_generate(args: argparse.Namespace) -> int:
    from .assembler import AssembleOptions, generate

    script = Path(args.script)
    if not script.is_file():
        _eprint(f"Error: no existe el guion {script}")
        return 2
    output = Path(args.output) if args.output else Path("output") / f"{script.stem}.mp3"
    options = AssembleOptions(
        engine_override=args.engine,
        sample_rate=args.sample_rate,
        target_lufs=None if args.no_normalize else args.lufs,
    )
    if args.no_cache:
        options.cache_dir = None
    elif args.cache_dir:
        options.cache_dir = Path(args.cache_dir)

    started = time.perf_counter()

    def progress(i: int, n: int, msg: str) -> None:
        if not args.quiet:
            _eprint(f"[{i}/{n}] {msg}")

    _eprint(f"Generando {output} a partir de {script}...")
    path = generate(
        script, output, voices_dir=args.voices_dir, options=options, progress=progress,
        max_chars=args.max_chars, bitrate=args.bitrate,
    )
    _eprint(f"Listo: {path} ({time.perf_counter() - started:.1f} s)")
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    script = parse_file(args.script, max_chars=args.max_chars)
    print(script.to_json(indent=None if args.compact else 2))
    return 0


def _cmd_voices_list(args: argparse.Namespace) -> int:
    from .voices import default_voices_dir, list_voices

    voices = list_voices(args.voices_dir)
    if args.json:
        data = [{**v.to_dict(), "path": str(v.path), "has_ref": v.has_ref} for v in voices]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    root = args.voices_dir or default_voices_dir()
    if not voices:
        print(f"No hay voces en {root}. Añade una con: python -m podcast_tts voices add ...")
        return 0
    print(f"Voces en {root}:")
    for v in voices:
        ref = "ref.wav" if v.has_ref else (f"speaker '{v.xtts_speaker}'" if v.xtts_speaker else "SIN ref.wav")
        desc = f" - {v.description}" if v.description else ""
        print(f"  {v.name:<16} lang={v.lang:<4} engine={v.engine:<5} speed={v.speed:<4g} {ref}{desc}")
    return 0


def _cmd_voices_add(args: argparse.Namespace) -> int:
    from .voices import add_voice

    transcript = args.text or ""
    if args.text_file:
        transcript = Path(args.text_file).read_text(encoding="utf-8-sig").strip()
    voice = add_voice(
        args.name, args.wav, transcript, lang=args.lang, engine=args.engine_voice,
        description=args.description, xtts_speaker=args.xtts_speaker, speed=args.speed,
        voices_dir=args.voices_dir, overwrite=args.overwrite,
    )
    print(f"Voz '{voice.name}' guardada en {voice.path}")
    return 0


def _cmd_voices_remove(args: argparse.Namespace) -> int:
    from .voices import remove_voice

    remove_voice(args.name, args.voices_dir)
    print(f"Voz '{args.name}' eliminada")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from .ui import run_from_args

    return run_from_args(args)


def _cmd_models_list(args: argparse.Namespace) -> int:
    from .models import MODELS

    if args.json:
        data = [
            {"name": m.name, "title": m.title, "repo_id": m.repo_id, "url": m.url,
             "approx_size": m.approx_size, "license": m.license, "commercial": m.commercial,
             "used_by": m.used_by, "optional": m.optional, "notes": m.notes}
            for m in MODELS
        ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print("Modelos de los motores locales (se descargan solos la primera vez que se usan):\n")
    for m in MODELS:
        comercial = "sí" if m.commercial else "NO"
        opt = " (opcional)" if m.optional else ""
        print(f"  {m.name:<11} {m.title}{opt}")
        print(f"              repo: {m.url}")
        print(f"              tamaño ~{m.approx_size} | licencia: {m.license} | uso comercial: {comercial}")
        print(f"              lo usa: {m.used_by}")
        if m.notes:
            print(f"              nota: {m.notes}")
    print("\nDescargar ya: podcast-tts models download all   |   Estado: podcast-tts models status")
    return 0


def _cmd_models_status(args: argparse.Namespace) -> int:
    from .models import MODELS, human_size, model_status

    rows = [model_status(m) for m in MODELS]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for m, st in zip(MODELS, rows):
        if st["downloaded"]:
            state = f"descargado ({human_size(st['size_bytes'])})"
        elif st["partial"]:
            state = f"INCOMPLETO (faltan {', '.join(st['missing'])})"
        else:
            state = "no descargado" + (" (opcional)" if m.optional else "")
        print(f"  {m.name:<11} {state}\n              {st['path']}")
    return 0


def _cmd_models_download(args: argparse.Namespace, update: bool = False) -> int:
    from .models import MODELS, download, model_status, resolve_names

    models = resolve_names(args.names)
    if update and not args.names:
        # `models update` a secas: solo lo que ya está descargado, opcionales incluidos
        models = [m for m in MODELS if model_status(m)["downloaded"]]
        if not models:
            print("No hay modelos descargados que actualizar (usa: podcast-tts models download).")
            return 0
    if any(m.storage == "coqui" for m in models):
        print("Aviso: XTTS v2 se distribuye bajo la Coqui Public Model License (uso NO comercial).")
    failed = []
    for m in models:
        try:
            download(m, force_check=update)
        except Exception as exc:  # noqa: BLE001 - seguir con el resto
            _eprint(f"  {m.name}: ERROR: {exc}")
            failed.append(m.name)
    if failed:
        _eprint(f"Fallaron: {', '.join(failed)}")
        return 1
    print("Modelos listos.")
    return 0


def _cmd_models_update(args: argparse.Namespace) -> int:
    return _cmd_models_download(args, update=True)


# --------------------------------------------------------------------------- #
# Argumentos
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="podcast_tts",
        description="Genera podcasts a partir de guiones Markdown con voces clonadas (F5-TTS / XTTS v2).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="comando")

    voices_dir = argparse.ArgumentParser(add_help=False)
    voices_dir.add_argument("--voices-dir", default=None,
                            help="directorio de voces (por defecto: <proyecto>/voices)")

    g = sub.add_parser("generate", parents=[voices_dir], help="genera el audio de un guion")
    g.add_argument("script", help="guion .md")
    g.add_argument("-o", "--output", help="fichero de salida .mp3/.wav (por defecto output/<guion>.mp3)")
    g.add_argument("--engine", choices=ENGINE_NAMES, default=None,
                   help="fuerza un motor para todas las voces (p.ej. dummy para probar)")
    g.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                   help=f"longitud máxima de cada trozo de texto (por defecto {DEFAULT_MAX_CHARS})")
    g.add_argument("--bitrate", default="192k", help="bitrate MP3 (por defecto 192k)")
    g.add_argument("--sample-rate", type=int, default=44100, help="frecuencia de salida (Hz)")
    g.add_argument("--lufs", type=float, default=-16.0, help="sonoridad objetivo (por defecto -16)")
    g.add_argument("--no-normalize", action="store_true", help="no normalizar la sonoridad")
    g.add_argument("--no-cache", action="store_true", help="no usar la caché de síntesis")
    g.add_argument("--cache-dir", default=None, help="directorio de caché (por defecto .cache/tts)")
    g.add_argument("-q", "--quiet", action="store_true", help="no mostrar el progreso")
    g.set_defaults(func=_cmd_generate)

    pa = sub.add_parser("parse", help="parsea un guion e imprime los segmentos en JSON")
    pa.add_argument("script", help="guion .md")
    pa.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    pa.add_argument("--compact", action="store_true", help="JSON en una sola línea")
    pa.set_defaults(func=_cmd_parse)

    v = sub.add_parser("voices", help="gestiona las voces")
    vsub = v.add_subparsers(dest="voices_command", required=True, metavar="acción")

    vl = vsub.add_parser("list", parents=[voices_dir], help="lista las voces")
    vl.add_argument("--json", action="store_true", help="salida en JSON")
    vl.set_defaults(func=_cmd_voices_list)

    va = vsub.add_parser("add", parents=[voices_dir], help="añade una voz a partir de un clip")
    va.add_argument("name", help="nombre de la voz (letras, números, _ o -)")
    va.add_argument("wav", nargs="?", default=None, help="clip de referencia (5-15 s; cualquier formato de ffmpeg)")
    va.add_argument("--text", default="", help="transcripción exacta del clip (necesaria para F5)")
    va.add_argument("--text-file", default=None, help="fichero con la transcripción")
    va.add_argument("--lang", default="es", help="idioma principal (es, en, ...)")
    va.add_argument("--engine", dest="engine_voice", default="f5", choices=ENGINE_NAMES,
                    help="motor por defecto de la voz")
    va.add_argument("--description", default="", help="descripción libre")
    va.add_argument("--xtts-speaker", default=None, help="speaker integrado de XTTS (en vez de clonar)")
    va.add_argument("--speed", type=float, default=1.0, help="velocidad por defecto")
    va.add_argument("--overwrite", action="store_true", help="sobrescribe si ya existe")
    va.set_defaults(func=_cmd_voices_add)

    vr = vsub.add_parser("remove", parents=[voices_dir], help="elimina una voz")
    vr.add_argument("name")
    vr.set_defaults(func=_cmd_voices_remove)

    u = sub.add_parser("ui", parents=[voices_dir], help="lanza la interfaz web local (Gradio)")
    u.add_argument("--port", type=int, default=7860, help="puerto (por defecto 7860)")
    u.add_argument("--host", default="127.0.0.1", help="interfaz de red (por defecto 127.0.0.1)")
    u.add_argument("--share", action="store_true", help="crea un enlace público temporal de Gradio")
    u.add_argument("--inbrowser", action="store_true", help="abre el navegador al arrancar")
    u.set_defaults(func=_cmd_ui)

    m = sub.add_parser("models", help="lista, comprueba y descarga los modelos de los motores locales")
    msub = m.add_subparsers(dest="models_command", required=True, metavar="acción")
    ml = msub.add_parser("list", help="modelos conocidos, repo de Hugging Face, tamaño y licencia")
    ml.add_argument("--json", action="store_true", help="salida en JSON")
    ml.set_defaults(func=_cmd_models_list)
    ms = msub.add_parser("status", help="si cada modelo está descargado, dónde y cuánto ocupa")
    ms.add_argument("--json", action="store_true", help="salida en JSON")
    ms.set_defaults(func=_cmd_models_status)
    md = msub.add_parser("download", help="descarga los modelos que falten (por defecto: all)")
    md.add_argument("names", nargs="*", metavar="nombre",
                    help="f5-base, f5-spanish, vocos, xtts, whisper o all (por defecto all; whisper es opcional)")
    md.set_defaults(func=_cmd_models_download)
    mu = msub.add_parser("update", help="baja la última revisión de los modelos ya descargados")
    mu.add_argument("names", nargs="*", metavar="nombre",
                    help="como en download (por defecto: solo los ya descargados)")
    mu.set_defaults(func=_cmd_models_update)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada; devuelve el código de salida."""
    _setup_console()
    args = build_parser().parse_args(argv)
    from .assembler import AssembleError
    from .engines import EngineError
    from .models import ModelsError
    from .voices import VoiceError

    try:
        return int(args.func(args) or 0)
    except ScriptParseError as exc:
        _eprint(f"Error en el guion: {exc}")
    except (VoiceError, AssembleError, EngineError, ModelsError) as exc:
        _eprint(f"Error: {exc}")
    except NotImplementedError as exc:
        _eprint(f"No implementado: {exc}")
    except FileNotFoundError as exc:
        _eprint(f"Error: fichero no encontrado: {exc.filename or exc}")
    except KeyboardInterrupt:
        _eprint("Cancelado.")
        return 130
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
