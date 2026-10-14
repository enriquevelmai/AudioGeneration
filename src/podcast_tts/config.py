"""API keys of the cloud engines (ElevenLabs, Azure, OpenAI...) and other settings.

Priority when reading a key:

1. Environment variable (``ELEVENLABS_API_KEY``, ``AZURE_SPEECH_KEY``...).
2. ``.env`` file at the project root (ignored by git). It can be changed with the
   ``PODCAST_TTS_ENV_FILE`` environment variable.

The same file also stores non-secret settings such as the UI language (``PODCAST_TTS_LANG``,
see :mod:`podcast_tts.i18n`).

Keys are NEVER printed or logged: use :func:`mask` to display them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "KNOWN_KEYS",
    "SECRET_KEYS",
    "ConfigError",
    "KeyStatus",
    "delete_key",
    "env_file_path",
    "get_key",
    "is_secret",
    "key_status",
    "mask",
    "read_env_file",
    "set_key",
    "unset_key",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Known variables -> description.
KNOWN_KEYS: dict[str, str] = {
    "ELEVENLABS_API_KEY": "ElevenLabs API key",
    "AZURE_SPEECH_KEY": "Azure AI Speech resource key",
    "AZURE_SPEECH_REGION": "Azure AI Speech resource region (e.g. westeurope)",
    "OPENAI_API_KEY": "OpenAI API key",
}
#: Variables that are not secret (shown unmasked).
_PUBLIC_KEYS = frozenset({"AZURE_SPEECH_REGION", "PODCAST_TTS_LANG"})
SECRET_KEYS: tuple[str, ...] = tuple(k for k in KNOWN_KEYS if k not in _PUBLIC_KEYS)

_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


class ConfigError(ValueError):
    """Invalid configuration name or value."""


@dataclass(frozen=True)
class KeyStatus:
    """Status of a variable: whether it is set, where it comes from and its masked value."""

    name: str
    description: str
    is_set: bool
    source: str | None  # "env" (environment variable), ".env" or None
    masked: str


def env_file_path() -> Path:
    """Path of the ``.env`` file: ``$PODCAST_TTS_ENV_FILE`` or ``<project>/.env``."""
    env = os.environ.get("PODCAST_TTS_ENV_FILE")
    return Path(env) if env else PROJECT_ROOT / ".env"


def _path(env_file: str | Path | None) -> Path:
    return Path(env_file) if env_file is not None else env_file_path()


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ConfigError(
            f"invalid variable name {name!r}: use uppercase letters, digits and '_' "
            "(e.g. OPENAI_API_KEY)"
        )
    return name


def _quoted_prefix(value: str) -> tuple[str, str] | None:
    """If ``value`` starts with a quote, return ``(content, rest)``; None if it is never closed."""
    quote = value[0]
    i = 1
    while i < len(value):
        ch = value[i]
        if quote == '"' and ch == "\\" and i + 1 < len(value):
            i += 2
            continue
        if ch == quote:
            return value[1:i], value[i + 1:]
        i += 1
    return None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] in "\"'":
        parsed = _quoted_prefix(value)
        # After the closing quote only spaces and, optionally, a comment are allowed.
        if parsed is not None and re.fullmatch(r"\s*(#.*)?", parsed[1]):
            inner = parsed[0]
            if value[0] == '"':
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            return inner
    # End-of-line comment only when preceded by whitespace (KEY=value # comment)
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _quote(value: str) -> str:
    if value and re.fullmatch(r"[A-Za-z0-9_\-.:/+=@,]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_env_file(env_file: str | Path | None = None) -> dict[str, str]:
    """Read ``KEY=value`` pairs from the ``.env`` file (comments and blank lines are ignored)."""
    path = _path(env_file)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return {}
    data: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if m:
            data[m.group(1)] = _unquote(m.group(2))
    return data


def get_key(name: str, env_file: str | Path | None = None) -> str | None:
    """Value of ``name`` (environment > ``.env``), or ``None`` if it is unset or empty."""
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    value = read_env_file(env_file).get(name)
    return value.strip() if value and value.strip() else None


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # on Windows this only affects the read-only bit
    except OSError:
        pass
    tmp.replace(path)


def set_key(name: str, value: str, env_file: str | Path | None = None) -> Path:
    """Save ``name=value`` in ``.env`` (replacing the line if it existed). Returns the path.

    ``os.environ`` is not modified: if the variable is also in the environment, that one wins.
    """
    name = _validate_name(name)
    value = (value or "").strip()
    if not value:
        raise ConfigError(f"the value of {name} is empty (to remove it use 'config unset')")
    if "\n" in value or "\r" in value:
        raise ConfigError(f"the value of {name} cannot contain line breaks")
    path = _path(env_file)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        lines = ["# podcast_tts API keys and settings (do NOT commit to git). See .env.example."]
    new_line = f"{name}={_quote(value)}"
    replaced = False
    out: list[str] = []
    for line in lines:
        m = _LINE_RE.match(line) if not line.lstrip().startswith("#") else None
        if m and m.group(1) == name:
            if not replaced:
                out.append(new_line)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append(new_line)
    _write_lines(path, out)
    return path


def delete_key(name: str, env_file: str | Path | None = None) -> bool:
    """Remove ``name`` from ``.env``. Returns ``True`` if it was there. The environment is untouched."""
    name = _validate_name(name)
    path = _path(env_file)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return False
    out = []
    found = False
    for line in lines:
        m = _LINE_RE.match(line) if not line.lstrip().startswith("#") else None
        if m and m.group(1) == name:
            found = True
            continue
        out.append(line)
    if found:
        _write_lines(path, out)
    return found


unset_key = delete_key  # alias


def is_secret(name: str) -> bool:
    """``True`` except for known public variables (e.g. the Azure region or the UI language)."""
    return name not in _PUBLIC_KEYS


def mask(value: str | None) -> str:
    """Mask a secret: ``sk-proj-abc...wxyz`` -> ``sk-...wxyz``.

    Short values (< 12 characters) are hidden completely.
    """
    if not value:
        return ""
    value = value.strip()
    if len(value) < 12:
        return "****"
    return f"{value[:3]}...{value[-4:]}"


def key_status(names: list[str] | tuple[str, ...] | None = None,
               env_file: str | Path | None = None) -> list[KeyStatus]:
    """Status of each variable (by default those in :data:`KNOWN_KEYS`), with masked values."""
    file_data = read_env_file(env_file)
    result = []
    for name in names or tuple(KNOWN_KEYS):
        env_value = os.environ.get(name, "").strip()
        file_value = (file_data.get(name) or "").strip()
        value, source = (env_value, "env") if env_value else (
            (file_value, ".env") if file_value else ("", None))
        shown = (mask(value) if is_secret(name) else value) if value else ""
        result.append(KeyStatus(name=name, description=KNOWN_KEYS.get(name, ""), is_set=bool(value),
                                source=source, masked=shown))
    return result
