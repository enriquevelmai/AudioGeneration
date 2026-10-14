"""Interfaz de línea de comandos.

Ejemplos::

    python -m podcast_tts generate guion.md -o output/episodio.mp3 [--engine dummy]
    python -m podcast_tts parse guion.md
    python -m podcast_tts voices list
    python -m podcast_tts voices add ana clip.wav --text "Transcripción del clip" --lang es
    python -m podcast_tts voices remove ana
    python -m podcast_tts ui [--port 7860] [--host 127.0.0.1] [--share]
    python -m podcast_tts engines [--json]
    python -m podcast_tts config show | set OPENAI_API_KEY | unset OPENAI_API_KEY
    python -m podcast_tts voices add nova --engine openai --provider-voice-id nova --lang es
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
from .engines import engine_names
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

    if not args.no_license_notice:
        _print_license_notice(script, args)
    _eprint(f"Generando {output} a partir de {script}...")
    path = generate(
        script, output, voices_dir=args.voices_dir, options=options, progress=progress,
        max_chars=args.max_chars, bitrate=args.bitrate,
    )
    _eprint(f"Listo: {path} ({time.perf_counter() - started:.1f} s)")
    return 0


def _print_license_notice(script_path: Path, args: argparse.Namespace) -> None:
    """Muestra (una vez) el aviso de licencia si el guion usa motores no comerciales."""
    from .licensing import engines_in_script, license_notice

    try:
        parsed = parse_file(script_path, max_chars=args.max_chars)
        names = engines_in_script(parsed, args.voices_dir, args.engine)
    except Exception:  # noqa: BLE001 - los errores reales se notifican al generar
        return
    notice = license_notice(names)
    if notice:
        _eprint(f"{notice} (Oculta este aviso con --no-license-notice.)")


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
        if v.provider_voice_id:
            ref = f"voz del proveedor '{v.provider_voice_id}'"
        else:
            ref = "ref.wav" if v.has_ref else (
                f"speaker '{v.xtts_speaker}'" if v.xtts_speaker else "SIN ref.wav")
        desc = f" - {v.description}" if v.description else ""
        print(f"  {v.name:<16} lang={v.lang:<4} engine={v.engine:<5} speed={v.speed:<4g} {ref}{desc}")
    return 0


def _cmd_voices_add(args: argparse.Namespace) -> int:
    from .voices import add_voice

    transcript = args.text or ""
    if args.text_file:
        transcript = Path(args.text_file).read_text(encoding="utf-8-sig").strip()
    options = _parse_provider_options(args.provider_option or [])
    voice = add_voice(
        args.name, args.wav, transcript, lang=args.lang, engine=args.engine_voice,
        description=args.description, xtts_speaker=args.xtts_speaker, speed=args.speed,
        voices_dir=args.voices_dir, overwrite=args.overwrite,
        provider_voice_id=args.provider_voice_id, provider_options=options or None,
    )
    print(f"Voz '{voice.name}' guardada en {voice.path}")
    return 0


def _parse_provider_options(items: list[str]) -> dict[str, object]:
    """``["model_id=eleven_turbo_v2_5", 'voice_settings={"stability": 0.4}']`` -> dict.

    Los valores se interpretan como JSON si es posible (números, booleanos, objetos).
    """
    from .voices import VoiceError

    options: dict[str, object] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise VoiceError(f"opción de proveedor inválida {item!r}: usa CLAVE=VALOR")
        try:
            options[key] = json.loads(raw)
        except ValueError:
            options[key] = raw
    return options


def _cmd_voices_remove(args: argparse.Namespace) -> int:
    from .voices import remove_voice

    remove_voice(args.name, args.voices_dir)
    print(f"Voz '{args.name}' eliminada")
    return 0


def _commercial_label(value: object) -> str:
    return "sí" if value is True else ("no" if value is False else str(value))


def _cmd_engines(args: argparse.Namespace) -> int:
    from .engines import engine_info

    info = engine_info(check_cuda=args.cuda)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"{'Motor':<12} {'Tipo':<6} {'Comercial':<17} {'Estado':<16} Licencia")
    for name, d in info.items():
        if not d["importable"]:
            state = "no disponible"
        elif not d["configured"]:
            state = "sin configurar"
        else:
            state = "listo"
        if args.cuda and d["kind"] == "local" and name != "dummy":
            state += " (GPU)" if d["cuda"] else " (CPU)"
        print(f"{name:<12} {d['kind']:<6} {_commercial_label(d['commercial_use']):<17} "
              f"{state:<16} {d['license']}")
        if d.get("missing_config"):
            print(f"{'':<12} falta: {', '.join(d['missing_config'])} "
                  f"(python -m podcast_tts config set {d['missing_config'][0]})")
        if d.get("error") and not d["importable"]:
            print(f"{'':<12} {d['error']}")
    print("\nLos pesos de f5 y xtts son de uso NO comercial. Ver docs/COMMERCIAL_USE.md.")
    return 0


def _config_names() -> list[str]:
    """Variables conocidas más las que piden los motores registrados (integrados y plugins)."""
    from .config import KNOWN_KEYS
    from .engines import EngineError, engine_class

    keys: list[str] = list(KNOWN_KEYS)
    for name in engine_names():
        try:
            req = getattr(engine_class(name), "required_config", ()) or ()
        except EngineError:
            continue
        keys += [str(k) for k in req if str(k) not in keys]
    return keys


def _cmd_config_show(args: argparse.Namespace) -> int:
    from .config import env_file_path, key_status

    print(f"Fichero .env: {env_file_path()}")
    for st in key_status(_config_names()):
        value = f"{st.masked} ({st.source})" if st.is_set else "(sin definir)"
        print(f"  {st.name:<22} {value}")
    print("Las variables de entorno tienen prioridad sobre el fichero .env.")
    return 0


def _cmd_config_set(args: argparse.Namespace) -> int:
    import getpass
    import os

    from .config import is_secret, mask, set_key

    name = args.name.strip().upper()
    if name not in _config_names():
        _eprint(f"Aviso: {name} no es una variable conocida; se guarda igualmente.")
    if is_secret(name):
        value = getpass.getpass(f"Valor de {name} (no se mostrará): ")
    else:
        value = input(f"Valor de {name}: ")
    path = set_key(name, value)
    shown = mask(value.strip()) if is_secret(name) else value.strip()
    print(f"{name} guardada en {path} ({shown})")
    if os.environ.get(name):
        _eprint(f"Aviso: {name} también está definida como variable de entorno y tiene prioridad.")
    return 0


def _cmd_config_unset(args: argparse.Namespace) -> int:
    import os

    from .config import delete_key, env_file_path

    name = args.name.strip().upper()
    if delete_key(name):
        print(f"{name} borrada de {env_file_path()}")
    else:
        print(f"{name} no estaba en {env_file_path()}")
    if os.environ.get(name):
        _eprint(f"Aviso: {name} sigue definida como variable de entorno; bórrala de tu sistema.")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from .ui import run_from_args

    return run_from_args(args)


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
    g.add_argument("--engine", choices=engine_names(), default=None,
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
    g.add_argument("--no-license-notice", action="store_true",
                   help="no mostrar el aviso de licencia de los motores no comerciales")
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
    va.add_argument("--engine", dest="engine_voice", default="f5", choices=engine_names(),
                    help="motor por defecto de la voz")
    va.add_argument("--description", default="", help="descripción libre")
    va.add_argument("--xtts-speaker", default=None, help="speaker integrado de XTTS (en vez de clonar)")
    va.add_argument("--speed", type=float, default=1.0, help="velocidad por defecto")
    va.add_argument("--overwrite", action="store_true", help="sobrescribe si ya existe")
    va.add_argument("--provider-voice-id", default=None,
                    help="ID o nombre de la voz en el proveedor (motores en la nube: elevenlabs, "
                         "azure, openai)")
    va.add_argument("--provider-option", action="append", metavar="CLAVE=VALOR",
                    help="opción del proveedor (repetible; el valor puede ser JSON), "
                         "p.ej. model_id=eleven_turbo_v2_5")
    va.set_defaults(func=_cmd_voices_add)

    vr = vsub.add_parser("remove", parents=[voices_dir], help="elimina una voz")
    vr.add_argument("name")
    vr.set_defaults(func=_cmd_voices_remove)

    e = sub.add_parser("engines", help="lista los motores: tipo, licencia, uso comercial y estado")
    e.add_argument("--json", action="store_true", help="salida en JSON")
    e.add_argument("--cuda", action="store_true", help="comprueba también la GPU (importa torch)")
    e.set_defaults(func=_cmd_engines)

    c = sub.add_parser("config", help="claves de API de los motores en la nube (.env)")
    csub = c.add_subparsers(dest="config_command", required=True, metavar="acción")
    cs = csub.add_parser("show", help="muestra las claves (enmascaradas)")
    cs.set_defaults(func=_cmd_config_show)
    cset = csub.add_parser("set", help="guarda una clave en .env (el valor se pide sin eco)")
    cset.add_argument("name", help="variable, p.ej. ELEVENLABS_API_KEY")
    cset.set_defaults(func=_cmd_config_set)
    cu = csub.add_parser("unset", help="borra una clave de .env")
    cu.add_argument("name", help="variable, p.ej. ELEVENLABS_API_KEY")
    cu.set_defaults(func=_cmd_config_unset)

    u = sub.add_parser("ui", parents=[voices_dir], help="lanza la interfaz web local (Gradio)")
    u.add_argument("--port", type=int, default=7860, help="puerto (por defecto 7860)")
    u.add_argument("--host", default="127.0.0.1", help="interfaz de red (por defecto 127.0.0.1)")
    u.add_argument("--share", action="store_true", help="crea un enlace público temporal de Gradio")
    u.add_argument("--inbrowser", action="store_true", help="abre el navegador al arrancar")
    u.set_defaults(func=_cmd_ui)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada; devuelve el código de salida."""
    _setup_console()
    args = build_parser().parse_args(argv)
    from .assembler import AssembleError
    from .config import ConfigError
    from .engines import EngineError
    from .voices import VoiceError

    try:
        return int(args.func(args) or 0)
    except ScriptParseError as exc:
        _eprint(f"Error en el guion: {exc}")
    except (VoiceError, AssembleError, EngineError, ConfigError) as exc:
        _eprint(f"Error: {exc}")
    except NotImplementedError as exc:
        _eprint(f"No implementado: {exc}")
    except FileNotFoundError as exc:
        _eprint(f"Error: fichero no encontrado: {exc.filename or exc}")
    except EOFError:
        _eprint("Cancelado: no se recibió ningún valor.")
    except KeyboardInterrupt:
        _eprint("Cancelado.")
        return 130
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
