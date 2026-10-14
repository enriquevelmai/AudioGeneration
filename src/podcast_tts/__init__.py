"""podcast_tts: generate podcasts from Markdown scripts with locally cloned voices."""

def _read_version() -> str:
    """Installed version (package metadata); fallback when running from src/ without installing."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("podcast-tts")
    except (ImportError, PackageNotFoundError):  # pragma: no cover - depends on the installation
        return "1.0.0"


__version__ = _read_version()

from ._warnings import silence_noisy_warnings  # noqa: E402

silence_noisy_warnings()

from .script_parser import (  # noqa: E402
    Music,
    ParsedScript,
    Pause,
    ScriptMeta,
    ScriptParseError,
    Segment,
    Sfx,
    Speech,
    parse_file,
    parse_script,
)
from .voices import Voice, add_voice, get_voice, list_voices, remove_voice  # noqa: E402

__all__ = [
    "Music",
    "ParsedScript",
    "Pause",
    "ScriptMeta",
    "ScriptParseError",
    "Segment",
    "Sfx",
    "Speech",
    "Voice",
    "__version__",
    "add_voice",
    "get_voice",
    "list_voices",
    "parse_file",
    "parse_script",
    "remove_voice",
]
