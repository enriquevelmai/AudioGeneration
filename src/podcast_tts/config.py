"""Claves de API de los motores en la nube (ElevenLabs, Azure, OpenAI...).

Orden de prioridad al leer una clave:

1. Variable de entorno (``ELEVENLABS_API_KEY``, ``AZURE_SPEECH_KEY``...).
2. Fichero ``.env`` en la raíz del proyecto (ignorado por git). Se puede cambiar
   con la variable de entorno ``PODCAST_TTS_ENV_FILE``.

Las claves NUNCA se imprimen ni se registran: para mostrarlas usa :func:`mask`.
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

#: Variables conocidas -> descripción (en castellano).
KNOWN_KEYS: dict[str, str] = {
    "ELEVENLABS_API_KEY": "Clave de API de ElevenLabs",
    "AZURE_SPEECH_KEY": "Clave del recurso Azure AI Speech",
    "AZURE_SPEECH_REGION": "Región del recurso Azure AI Speech (p.ej. westeurope)",
    "OPENAI_API_KEY": "Clave de API de OpenAI",
}
#: Variables que no son secretas (se muestran sin enmascarar).
_PUBLIC_KEYS = frozenset({"AZURE_SPEECH_REGION"})
SECRET_KEYS: tuple[str, ...] = tuple(k for k in KNOWN_KEYS if k not in _PUBLIC_KEYS)

_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


class ConfigError(ValueError):
    """Nombre o valor de configuración inválido."""


@dataclass(frozen=True)
class KeyStatus:
    """Estado de una variable: si está definida, de dónde sale y su valor enmascarado."""

    name: str
    description: str
    is_set: bool
    source: str | None  # "entorno", ".env" o None
    masked: str


def env_file_path() -> Path:
    """Ruta del fichero ``.env``: ``$PODCAST_TTS_ENV_FILE`` o ``<proyecto>/.env``."""
    env = os.environ.get("PODCAST_TTS_ENV_FILE")
    return Path(env) if env else PROJECT_ROOT / ".env"


def _path(env_file: str | Path | None) -> Path:
    return Path(env_file) if env_file is not None else env_file_path()


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ConfigError(
            f"nombre de variable inválido {name!r}: usa mayúsculas, números y '_' (p.ej. OPENAI_API_KEY)"
        )
    return name


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    # Comentario al final de línea solo si va precedido de espacio (KEY=valor # comentario)
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _quote(value: str) -> str:
    if value and re.fullmatch(r"[A-Za-z0-9_\-.:/+=@,]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_env_file(env_file: str | Path | None = None) -> dict[str, str]:
    """Lee ``KEY=valor`` del fichero ``.env`` (ignora comentarios y líneas vacías)."""
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
    """Valor de ``name`` (entorno > ``.env``) o ``None`` si no está definido o está vacío."""
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
        os.chmod(tmp, 0o600)  # en Windows solo afecta al bit de solo lectura
    except OSError:
        pass
    tmp.replace(path)


def set_key(name: str, value: str, env_file: str | Path | None = None) -> Path:
    """Guarda ``name=value`` en ``.env`` (sustituye la línea si ya existía). Devuelve la ruta.

    No modifica ``os.environ``: si la variable también está en el entorno, esa tiene prioridad.
    """
    name = _validate_name(name)
    value = (value or "").strip()
    if not value:
        raise ConfigError(f"el valor de {name} está vacío (para borrarla usa 'config unset')")
    if "\n" in value or "\r" in value:
        raise ConfigError(f"el valor de {name} no puede contener saltos de línea")
    path = _path(env_file)
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        lines = ["# Claves de API de podcast_tts (NO subir a git). Ver .env.example."]
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
    """Borra ``name`` del ``.env``. Devuelve ``True`` si estaba. No toca el entorno."""
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
    """``True`` salvo para variables públicas conocidas (p.ej. la región de Azure)."""
    return name not in _PUBLIC_KEYS


def mask(value: str | None) -> str:
    """Enmascara un secreto: ``sk-proj-abc...wxyz`` -> ``sk-...wxyz``.

    Los valores cortos (< 12 caracteres) se ocultan por completo.
    """
    if not value:
        return ""
    value = value.strip()
    if len(value) < 12:
        return "****"
    return f"{value[:3]}...{value[-4:]}"


def key_status(names: list[str] | tuple[str, ...] | None = None,
               env_file: str | Path | None = None) -> list[KeyStatus]:
    """Estado de cada variable (por defecto las de :data:`KNOWN_KEYS`), con el valor enmascarado."""
    file_data = read_env_file(env_file)
    result = []
    for name in names or tuple(KNOWN_KEYS):
        env_value = os.environ.get(name, "").strip()
        file_value = (file_data.get(name) or "").strip()
        value, source = (env_value, "entorno") if env_value else (
            (file_value, ".env") if file_value else ("", None))
        shown = (mask(value) if is_secret(name) else value) if value else ""
        result.append(KeyStatus(name=name, description=KNOWN_KEYS.get(name, ""), is_set=bool(value),
                                source=source, masked=shown))
    return result
