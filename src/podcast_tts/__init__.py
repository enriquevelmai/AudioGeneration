"""podcast_tts: genera podcasts desde guiones Markdown con voces clonadas en local."""

__version__ = "0.1.0"

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
