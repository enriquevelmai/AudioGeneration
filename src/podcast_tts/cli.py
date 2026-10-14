"""Command-line interface.

Messages and help texts follow the UI language (English by default; set
``PODCAST_TTS_LANG=es`` or save it with ``config set PODCAST_TTS_LANG`` for Spanish).

Examples::

    python -m podcast_tts generate script.md -o output/episode.mp3 [--engine dummy]
    python -m podcast_tts parse script.md
    python -m podcast_tts voices list
    python -m podcast_tts voices add ana clip.wav --text "Transcript of the clip" --lang es
    python -m podcast_tts voices remove ana
    python -m podcast_tts ui [--port 7860] [--host 127.0.0.1] [--share] [--auth user:password]
    python -m podcast_tts desktop [--browser] [--debug]
    python -m podcast_tts mcp [--output-dir DIR]   (stdio MCP server for AI assistants)
    python -m podcast_tts engines [--json]
    python -m podcast_tts config show | set OPENAI_API_KEY | unset OPENAI_API_KEY
    python -m podcast_tts voices add nova --engine openai --provider-voice-id nova --lang en
    python -m podcast_tts models list|status [--json]
    python -m podcast_tts models download [f5-base|f5-spanish|vocos|xtts|whisper|all]
    python -m podcast_tts models update [name|all]
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
from .i18n import ENV_VAR as LANG_ENV_VAR
from .i18n import t
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
    warnings.formatwarning = lambda msg, cat, *a, **k: t("common.warning", msg=msg) + "\n"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def _cmd_generate(args: argparse.Namespace) -> int:
    from .assembler import AssembleOptions, generate

    script = Path(args.script)
    if not script.is_file():
        _eprint(t("cli.script_not_found", path=script))
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
    _eprint(t("cli.generating", output=output, script=script))
    info: dict[str, float] = {}
    path = generate(
        script, output, voices_dir=args.voices_dir, options=options, progress=progress,
        max_chars=args.max_chars, bitrate=args.bitrate, info=info,
    )
    elapsed = time.perf_counter() - started
    if "duration" in info:
        _eprint(t("cli.done_duration", path=path, duration=info["duration"], elapsed=elapsed))
    else:
        _eprint(t("cli.done", path=path, elapsed=elapsed))
    return 0


def _print_license_notice(script_path: Path, args: argparse.Namespace) -> None:
    """Print (once) the license notice if the script uses non-commercial engines."""
    from .licensing import engines_in_script, license_notice

    try:
        parsed = parse_file(script_path, max_chars=args.max_chars)
        names = engines_in_script(parsed, args.voices_dir, args.engine)
    except Exception:  # noqa: BLE001 - real errors are reported when generating
        return
    notice = license_notice(names)
    if notice:
        _eprint(f"{notice} {t('cli.hide_notice')}")


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
        print(t("cli.no_voices", root=root))
        return 0
    print(t("cli.voices_in", root=root))
    for v in voices:
        if v.provider_voice_id:
            ref = t("cli.provider_voice", id=v.provider_voice_id)
        else:
            ref = "ref.wav" if v.has_ref else (
                f"speaker '{v.xtts_speaker}'" if v.xtts_speaker else t("cli.no_ref"))
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
    print(t("cli.voice_saved", name=voice.name, path=voice.path))
    return 0


def _parse_provider_options(items: list[str]) -> dict[str, object]:
    """``["model_id=eleven_turbo_v2_5", 'voice_settings={"stability": 0.4}']`` -> dict.

    Values are parsed as JSON when possible (numbers, booleans, objects).
    """
    from .voices import VoiceError

    options: dict[str, object] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise VoiceError(f"invalid provider option {item!r}: use KEY=VALUE")
        try:
            options[key] = json.loads(raw)
        except ValueError:
            options[key] = raw
    return options


def _cmd_voices_remove(args: argparse.Namespace) -> int:
    from .voices import remove_voice

    remove_voice(args.name, args.voices_dir)
    print(t("cli.voice_removed", name=args.name))
    return 0


def _commercial_label(value: object) -> str:
    from .engines import COMMERCIAL_DEPENDS

    if value == COMMERCIAL_DEPENDS:
        return t("common.depends_on_plan")
    return t("common.yes") if value is True else (t("common.no") if value is False else str(value))


def _cmd_engines(args: argparse.Namespace) -> int:
    from .engines import engine_info

    info = engine_info(check_cuda=args.cuda)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"{t('cli.col_engine'):<12} {t('cli.col_type'):<6} {t('cli.col_commercial'):<17} "
          f"{t('cli.col_status'):<16} {t('cli.col_license')}")
    for name, d in info.items():
        if not d["importable"]:
            state = t("cli.state_unavailable")
        elif not d["configured"]:
            state = t("cli.state_unconfigured")
        else:
            state = t("cli.state_ready")
        if args.cuda and d["kind"] == "local" and name != "dummy":
            state += " (GPU)" if d["cuda"] else " (CPU)"
        print(f"{name:<12} {d['kind']:<6} {_commercial_label(d['commercial_use']):<17} "
              f"{state:<16} {d['license']}")
        if d.get("missing_config"):
            print(f"{'':<12} " + t("cli.missing_config", names=", ".join(d["missing_config"]),
                                   first=d["missing_config"][0]))
        if d.get("error") and not d["importable"]:
            print(f"{'':<12} {d['error']}")
    print(t("cli.engines_footer"))
    return 0


def _config_names() -> list[str]:
    """Known variables, the ones required by registered engines (built-in and plugins) and
    the UI language setting."""
    from .config import KNOWN_KEYS
    from .engines import EngineError, engine_class

    keys: list[str] = list(KNOWN_KEYS)
    for name in engine_names():
        try:
            req = getattr(engine_class(name), "required_config", ()) or ()
        except EngineError:
            continue
        keys += [str(k) for k in req if str(k) not in keys]
    keys.append(LANG_ENV_VAR)
    return keys


def _cmd_config_show(args: argparse.Namespace) -> int:
    from .config import env_file_path, key_status

    print(t("cli.env_file", path=env_file_path()))
    for st in key_status(_config_names()):
        value = f"{st.masked} ({st.source})" if st.is_set else t("cli.not_set")
        print(f"  {st.name:<22} {value}")
    print(t("cli.env_priority"))
    return 0


def _cmd_config_set(args: argparse.Namespace) -> int:
    import getpass
    import os

    from .config import ConfigError, is_secret, mask, set_key
    from .i18n import available_languages, normalize_language

    name = args.name.strip().upper()
    if name not in _config_names():
        _eprint(t("cli.unknown_var", name=name))
    if is_secret(name):
        value = getpass.getpass(t("cli.prompt_secret", name=name))
    else:
        value = input(t("cli.prompt_value", name=name))
    if name == LANG_ENV_VAR:
        code = normalize_language(value)
        if code is None:
            raise ConfigError(f"unsupported language {value.strip()!r} "
                              f"(available: {', '.join(available_languages())})")
        value = code
    path = set_key(name, value)
    shown = mask(value.strip()) if is_secret(name) else value.strip()
    print(t("cli.key_saved", name=name, path=path, shown=shown))
    if os.environ.get(name):
        _eprint(t("cli.env_also_set", name=name))
    return 0


def _cmd_config_unset(args: argparse.Namespace) -> int:
    import os

    from .config import delete_key, env_file_path

    name = args.name.strip().upper()
    if delete_key(name):
        print(t("cli.key_deleted", name=name, path=env_file_path()))
    else:
        print(t("cli.key_absent", name=name, path=env_file_path()))
    if os.environ.get(name):
        _eprint(t("cli.env_still_set", name=name))
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from .ui import run_from_args

    return run_from_args(args)


def _cmd_desktop(args: argparse.Namespace) -> int:
    from .desktop import run_from_args

    return run_from_args(args)


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import ServerConfig, run

    kwargs: dict[str, object] = {}
    if args.output_dir:
        kwargs["output_dir"] = Path(args.output_dir)
    if args.voices_dir:
        kwargs["voices_dir"] = Path(args.voices_dir)
    return run(ServerConfig(**kwargs))  # type: ignore[arg-type]


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
    print(t("cli.models_intro"))
    for m in MODELS:
        commercial = t("common.yes") if m.commercial else t("common.NO")
        opt = t("common.optional") if m.optional else ""
        print(f"  {m.name:<11} {m.title}{opt}")
        print(f"              repo: {m.url}")
        print("              " + t("cli.models_size", size=m.approx_size, license=m.license,
                                     commercial=commercial))
        print("              " + t("cli.models_used_by", used_by=m.used_by))
        if m.notes:
            print("              " + t("cli.models_note", note=m.notes))
    print(t("cli.models_footer"))
    return 0


def _cmd_models_status(args: argparse.Namespace) -> int:
    from .models import MODELS, human_size, model_status

    rows = [model_status(m) for m in MODELS]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for m, st in zip(MODELS, rows):
        if st["downloaded"]:
            state = t("cli.model_downloaded", size=human_size(st["size_bytes"]))
        elif st["partial"]:
            state = t("cli.model_partial", files=", ".join(st["missing"]))
        else:
            state = t("cli.model_missing") + (t("common.optional") if m.optional else "")
        print(f"  {m.name:<11} {state}\n              {st['path']}")
    return 0


def _cmd_models_download(args: argparse.Namespace, update: bool = False) -> int:
    from .models import MODELS, download, model_status, resolve_names

    models = resolve_names(args.names)
    if update and not args.names:
        # Plain `models update`: only what is already downloaded, optional models included
        models = [m for m in MODELS if model_status(m)["downloaded"]]
        if not models:
            print(t("cli.models_nothing_to_update"))
            return 0
    if any(m.storage == "coqui" for m in models):
        print(t("cli.xtts_license"))
    failed = []
    for m in models:
        try:
            download(m, force_check=update)
        except Exception as exc:  # noqa: BLE001 - carry on with the rest
            _eprint(f"  {m.name}: ERROR: {exc}")
            failed.append(m.name)
    if failed:
        _eprint(t("cli.models_failed", names=", ".join(failed)))
        return 1
    print(t("cli.models_ready"))
    return 0


def _cmd_models_update(args: argparse.Namespace) -> int:
    return _cmd_models_download(args, update=True)


# --------------------------------------------------------------------------- #
# Arguments
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="podcast_tts", description=t("cli.h_description"))
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar=t("cli.mv_command"))

    voices_dir = argparse.ArgumentParser(add_help=False)
    voices_dir.add_argument("--voices-dir", default=None, help=t("common.voices_dir_help"))

    g = sub.add_parser("generate", parents=[voices_dir], help=t("cli.h_generate"))
    g.add_argument("script", help=t("cli.h_script"))
    g.add_argument("-o", "--output", help=t("cli.h_output"))
    g.add_argument("--engine", choices=engine_names(), default=None, help=t("cli.h_engine"))
    g.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                   help=t("cli.h_max_chars", n=DEFAULT_MAX_CHARS))
    g.add_argument("--bitrate", default="192k", help=t("cli.h_bitrate"))
    g.add_argument("--sample-rate", type=int, default=44100, help=t("cli.h_sample_rate"))
    g.add_argument("--lufs", type=float, default=-16.0, help=t("cli.h_lufs"))
    g.add_argument("--no-normalize", action="store_true", help=t("cli.h_no_normalize"))
    g.add_argument("--no-cache", action="store_true", help=t("cli.h_no_cache"))
    g.add_argument("--cache-dir", default=None, help=t("cli.h_cache_dir"))
    g.add_argument("-q", "--quiet", action="store_true", help=t("cli.h_quiet"))
    g.add_argument("--no-license-notice", action="store_true",
                   help=t("cli.h_no_license_notice"))
    g.set_defaults(func=_cmd_generate)

    pa = sub.add_parser("parse", help=t("cli.h_parse"))
    pa.add_argument("script", help=t("cli.h_script"))
    pa.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    pa.add_argument("--compact", action="store_true", help=t("cli.h_compact"))
    pa.set_defaults(func=_cmd_parse)

    v = sub.add_parser("voices", help=t("cli.h_voices"))
    vsub = v.add_subparsers(dest="voices_command", required=True, metavar=t("cli.mv_action"))

    vl = vsub.add_parser("list", parents=[voices_dir], help=t("cli.h_voices_list"))
    vl.add_argument("--json", action="store_true", help=t("common.json_output"))
    vl.set_defaults(func=_cmd_voices_list)

    va = vsub.add_parser("add", parents=[voices_dir], help=t("cli.h_voices_add"))
    va.add_argument("name", help=t("cli.h_voice_name"))
    va.add_argument("wav", nargs="?", default=None, help=t("cli.h_wav"))
    va.add_argument("--text", default="", help=t("cli.h_text"))
    va.add_argument("--text-file", default=None, help=t("cli.h_text_file"))
    va.add_argument("--lang", default="es", help=t("cli.h_lang"))
    va.add_argument("--engine", dest="engine_voice", default="f5", choices=engine_names(),
                    help=t("cli.h_voice_engine"))
    va.add_argument("--description", default="", help=t("cli.h_description_free"))
    va.add_argument("--xtts-speaker", default=None, help=t("cli.h_xtts_speaker"))
    va.add_argument("--speed", type=float, default=1.0, help=t("cli.h_speed"))
    va.add_argument("--overwrite", action="store_true", help=t("cli.h_overwrite"))
    va.add_argument("--provider-voice-id", default=None, help=t("cli.h_provider_voice_id"))
    va.add_argument("--provider-option", action="append", metavar=t("cli.mv_key_value"),
                    help=t("cli.h_provider_option"))
    va.set_defaults(func=_cmd_voices_add)

    vr = vsub.add_parser("remove", parents=[voices_dir], help=t("cli.h_voices_remove"))
    vr.add_argument("name")
    vr.set_defaults(func=_cmd_voices_remove)

    e = sub.add_parser("engines", help=t("cli.h_engines"))
    e.add_argument("--json", action="store_true", help=t("common.json_output"))
    e.add_argument("--cuda", action="store_true", help=t("cli.h_cuda"))
    e.set_defaults(func=_cmd_engines)

    c = sub.add_parser("config", help=t("cli.h_config"))
    csub = c.add_subparsers(dest="config_command", required=True, metavar=t("cli.mv_action"))
    cs = csub.add_parser("show", help=t("cli.h_config_show"))
    cs.set_defaults(func=_cmd_config_show)
    cset = csub.add_parser("set", help=t("cli.h_config_set"))
    cset.add_argument("name", help=t("cli.h_variable"))
    cset.set_defaults(func=_cmd_config_set)
    cu = csub.add_parser("unset", help=t("cli.h_config_unset"))
    cu.add_argument("name", help=t("cli.h_variable"))
    cu.set_defaults(func=_cmd_config_unset)

    u =sub.add_parser("ui", parents=[voices_dir], help=t("cli.h_ui"))
    u.add_argument("--port", type=int, default=7860, help=t("cli.h_port"))
    u.add_argument("--host", default="127.0.0.1", help=t("cli.h_host"))
    u.add_argument("--share", action="store_true", help=t("cli.h_share"))
    u.add_argument("--auth", default=None, metavar=t("cli.mv_user_pass"),
                   help=t("cli.h_auth", env="PODCAST_TTS_AUTH"))  # = ui.AUTH_ENV
    u.add_argument("--inbrowser", action="store_true", help=t("cli.h_inbrowser"))
    u.set_defaults(func=_cmd_ui)

    from .desktop import build_arg_parser as desktop_args

    dk = sub.add_parser("desktop", parents=[voices_dir], help=t("cli.h_desktop"))
    desktop_args(dk)
    dk.set_defaults(func=_cmd_desktop)

    mc = sub.add_parser("mcp", parents=[voices_dir], help=t("cli.h_mcp"))
    mc.add_argument("--output-dir", default=None, help=t("cli.h_output_dir"))
    mc.set_defaults(func=_cmd_mcp)

    m = sub.add_parser("models", help=t("cli.h_models"))
    msub = m.add_subparsers(dest="models_command", required=True, metavar=t("cli.mv_action"))
    ml = msub.add_parser("list", help=t("cli.h_models_list"))
    ml.add_argument("--json", action="store_true", help=t("common.json_output"))
    ml.set_defaults(func=_cmd_models_list)
    ms = msub.add_parser("status", help=t("cli.h_models_status"))
    ms.add_argument("--json", action="store_true", help=t("common.json_output"))
    ms.set_defaults(func=_cmd_models_status)
    md = msub.add_parser("download", help=t("cli.h_models_download"))
    md.add_argument("names", nargs="*", metavar=t("cli.mv_name"), help=t("cli.h_models_names"))
    md.set_defaults(func=_cmd_models_download)
    mu = msub.add_parser("update", help=t("cli.h_models_update"))
    mu.add_argument("names", nargs="*", metavar=t("cli.mv_name"),
                    help=t("cli.h_models_update_names"))
    mu.set_defaults(func=_cmd_models_update)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the exit code."""
    _setup_console()
    args = build_parser().parse_args(argv)
    from .assembler import AssembleError
    from .config import ConfigError
    from .engines import EngineError
    from .models import ModelsError
    from .voices import VoiceError

    try:
        return int(args.func(args) or 0)
    except ScriptParseError as exc:
        _eprint(t("cli.err_script", exc=exc))
    except (VoiceError, AssembleError, EngineError, ConfigError, ModelsError) as exc:
        _eprint(t("cli.err_generic", exc=exc))
    except NotImplementedError as exc:
        _eprint(t("cli.err_not_implemented", exc=exc))
    except FileNotFoundError as exc:
        _eprint(t("cli.err_file_not_found", file=exc.filename or exc))
    except EOFError:
        _eprint(t("cli.cancelled_no_value"))
    except KeyboardInterrupt:
        _eprint(t("cli.cancelled"))
        return 130
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
