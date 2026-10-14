"""podcast_tts: genera podcasts desde guiones Markdown con voces clonadas en local."""

def _read_version() -> str:
    """Versión instalada (metadatos del paquete); fallback si se ejecuta desde src/ sin instalar."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("podcast-tts")
    except (ImportError, PackageNotFoundError):  # pragma: no cover - depende de la instalación
        return "1.0.0"


__version__ = _read_version()

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
