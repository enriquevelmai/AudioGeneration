"""Parser del formato de guion: Markdown con etiquetas entre corchetes.

Ejemplo::

    ---
    title: Mi episodio
    lang: es
    default_voice: ana
    ---
    # Esto es un comentario / encabezado: no se sintetiza
    [voz:ana] Hola y bienvenidos. [pausa:1.5]
    [voz:carlos lang=en speed=0.95] Hi everyone!
    [musica:intro.mp3 fondo vol=0.15]
    ...
    [musica:stop]

El resultado es un :class:`ParsedScript` con metadatos (:class:`ScriptMeta`)
y una lista de segmentos (:class:`Speech`, :class:`Pause`, :class:`Music`,
:class:`Sfx`).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Union

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_PARAGRAPH_PAUSE",
    "KNOWN_ENGINES",
    "Music",
    "ParsedScript",
    "Pause",
    "ScriptMeta",
    "ScriptParseError",
    "Segment",
    "Sfx",
    "Speech",
    "chunk_text",
    "known_engines",
    "parse_file",
    "parse_script",
    "segment_from_dict",
    "segment_to_dict",
    "split_sentences",
]

DEFAULT_MAX_CHARS = 250
DEFAULT_PARAGRAPH_PAUSE = 0.4
DEFAULT_MUSIC_VOLUME = 1.0
DEFAULT_BG_VOLUME = 0.15
DEFAULT_BG_FADE = 1.5
DEFAULT_SFX_VOLUME = 1.0


def known_engines() -> tuple[str, ...]:
    """Motores válidos en los guiones: integrados + plugins (ver :mod:`podcast_tts.engines`)."""
    from .engines import engine_names

    return engine_names()


def __getattr__(attr: str) -> Any:  # PEP 562: KNOWN_ENGINES dinámico (compatibilidad)
    if attr == "KNOWN_ENGINES":
        return known_engines()
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


class ScriptParseError(ValueError):
    """Error de sintaxis en el guion (incluye el número de línea si se conoce)."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        self.message = message
        super().__init__(f"Línea {line}: {message}" if line else message)


# --------------------------------------------------------------------------- #
# Modelos de datos
# --------------------------------------------------------------------------- #


@dataclass
class Speech:
    """Fragmento de texto a sintetizar con una voz.

    ``lang``, ``speed`` y ``engine`` a ``None`` significan "usar el valor de la
    voz (voice.json) o el global del guion".
    """

    voice: str
    text: str
    lang: str | None = None
    speed: float | None = None
    engine: str | None = None
    line: int | None = None


@dataclass
class Pause:
    """Silencio de ``seconds`` segundos."""

    seconds: float
    line: int | None = None


@dataclass
class Music:
    """Clip musical.

    - ``background=False``: se inserta en la línea temporal (avanza el tiempo).
    - ``background=True``: suena bajo las voces siguientes hasta un ``stop``.
    - ``stop=True``: detiene la música de fondo activa (``fade`` = fundido de salida).
    """

    path: str = ""
    volume: float = DEFAULT_MUSIC_VOLUME
    fade: float = 0.0
    background: bool = False
    stop: bool = False
    line: int | None = None


@dataclass
class Sfx:
    """Efecto puntual: se superpone a partir de la posición actual (no avanza el tiempo)."""

    path: str
    volume: float = DEFAULT_SFX_VOLUME
    line: int | None = None


Segment = Union[Speech, Pause, Music, Sfx]

_SEGMENT_TYPES: dict[str, type] = {
    "speech": Speech,
    "pause": Pause,
    "music": Music,
    "sfx": Sfx,
}
_TYPE_NAMES: dict[type, str] = {v: k for k, v in _SEGMENT_TYPES.items()}


@dataclass
class ScriptMeta:
    """Metadatos del guion (front matter YAML + etiquetas ``[titulo:...]``)."""

    title: str | None = None
    lang: str | None = None
    default_voice: str | None = None
    default_engine: str | None = None
    paragraph_pause: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedScript:
    """Resultado del parseo: metadatos + segmentos."""

    meta: ScriptMeta = field(default_factory=ScriptMeta)
    segments: list[Segment] = field(default_factory=list)

    @property
    def voices(self) -> list[str]:
        """Voces usadas, en orden de aparición."""
        seen: list[str] = []
        for seg in self.segments:
            if isinstance(seg, Speech) and seg.voice not in seen:
                seen.append(seg.voice)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": asdict(self.meta),
            "segments": [segment_to_dict(s) for s in self.segments],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParsedScript":
        meta_data = dict(data.get("meta") or {})
        known = set(ScriptMeta.__dataclass_fields__)
        extra = dict(meta_data.pop("extra", None) or {})
        for key in list(meta_data):
            if key not in known:
                extra[key] = meta_data.pop(key)
        meta = ScriptMeta(**meta_data, extra=extra)
        segments = [segment_from_dict(s) for s in data.get("segments") or []]
        return cls(meta=meta, segments=segments)

    @classmethod
    def from_json(cls, text: str) -> "ParsedScript":
        return cls.from_dict(json.loads(text))


def segment_to_dict(seg: Segment) -> dict[str, Any]:
    """Serializa un segmento a dict con clave ``type``."""
    try:
        type_name = _TYPE_NAMES[type(seg)]
    except KeyError as exc:  # pragma: no cover - defensivo
        raise TypeError(f"Segmento no soportado: {seg!r}") from exc
    return {"type": type_name, **asdict(seg)}


def segment_from_dict(data: dict[str, Any]) -> Segment:
    """Reconstruye un segmento desde un dict con clave ``type``."""
    data = dict(data)
    type_name = data.pop("type", None)
    if type_name not in _SEGMENT_TYPES:
        raise ValueError(f"Tipo de segmento desconocido: {type_name!r}")
    cls = _SEGMENT_TYPES[type_name]
    fields = cls.__dataclass_fields__
    return cls(**{k: v for k, v in data.items() if k in fields})


# --------------------------------------------------------------------------- #
# Troceado de texto
# --------------------------------------------------------------------------- #

# Fin de frase: . ! ? … seguido (opcionalmente) de comillas/paréntesis y espacio.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'”»)\]]*\s+")
_SOFT_BREAK = re.compile(r"(?<=[,;:—–])\s+")


def split_sentences(text: str) -> list[str]:
    """Divide en frases por ``. ! ? …`` y saltos de línea."""
    sentences: list[str] = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        pos = 0
        for m in _SENTENCE_END.finditer(line):
            piece = line[pos:m.end()].strip()
            if piece:
                sentences.append(piece)
            pos = m.end()
        rest = line[pos:].strip()
        if rest:
            sentences.append(rest)
    return sentences


def _pack(pieces: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _split_long(sentence: str, max_chars: int) -> list[str]:
    """Parte una frase demasiado larga por comas/;/: y, en último caso, por palabras."""
    out: list[str] = []
    for part in _SOFT_BREAK.split(sentence):
        if len(part) <= max_chars:
            out.append(part)
            continue
        current = ""
        for word in part.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) > max_chars and current:
                out.append(current)
                current = word
            else:
                current = candidate
        if current:
            out.append(current)
    return _pack(out, max_chars)


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Agrupa frases en trozos de como máximo ``max_chars`` sin cortar frases.

    Solo si una frase supera por sí sola ``max_chars`` se divide por comas o,
    en último caso, por palabras.
    """
    if max_chars <= 0:
        raise ValueError("max_chars debe ser > 0")
    pieces: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) > max_chars:
            pieces.extend(_split_long(sentence, max_chars))
        else:
            pieces.append(sentence)
    return _pack(pieces, max_chars)


# --------------------------------------------------------------------------- #
# Front matter
# --------------------------------------------------------------------------- #


def _coerce_scalar(value: str) -> Any:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false",):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _parse_front_matter_simple(block: str, start_line: int) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for offset, raw in enumerate(block.splitlines()):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ScriptParseError(
                f"front matter: se esperaba 'clave: valor', encontrado {raw!r}",
                start_line + offset,
            )
        key, value = line.split(":", 1)
        data[key.strip()] = _coerce_scalar(value)
    return data


def _parse_front_matter(block: str, start_line: int) -> dict[str, Any]:
    """Usa PyYAML si está instalado; si no, un parser trivial ``clave: valor``."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return _parse_front_matter_simple(block, start_line)
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        raise ScriptParseError(f"front matter YAML inválido: {exc}", start_line) from exc
    if not isinstance(data, dict):
        raise ScriptParseError("el front matter debe ser un mapa clave: valor", start_line)
    return {str(k): v for k, v in data.items()}


_META_ALIASES = {
    "title": "title",
    "titulo": "title",
    "título": "title",
    "lang": "lang",
    "idioma": "lang",
    "default_voice": "default_voice",
    "voz": "default_voice",
    "voice": "default_voice",
    "engine": "default_engine",
    "motor": "default_engine",
    "default_engine": "default_engine",
    "paragraph_pause": "paragraph_pause",
    "pausa_parrafo": "paragraph_pause",
    "pausa_párrafo": "paragraph_pause",
}


def _build_meta(data: dict[str, Any], line: int) -> ScriptMeta:
    meta = ScriptMeta()
    for key, value in data.items():
        target = _META_ALIASES.get(key.lower())
        if target is None:
            meta.extra[key] = value
        elif target == "paragraph_pause":
            try:
                meta.paragraph_pause = float(value)
            except (TypeError, ValueError) as exc:
                raise ScriptParseError(f"'{key}' debe ser un número", line) from exc
        else:
            setattr(meta, target, None if value is None else str(value))
    if meta.default_engine:
        meta.default_engine = meta.default_engine.lower()
        valid = known_engines()
        if meta.default_engine not in valid:
            raise ScriptParseError(
                f"motor desconocido '{meta.default_engine}' "
                f"(válidos: {', '.join(valid)})",
                line,
            )
    return meta


# --------------------------------------------------------------------------- #
# Etiquetas
# --------------------------------------------------------------------------- #

_TAG_RE = re.compile(r"\[([^\[\]\n]*)\]")
_TAG_HEAD_RE = re.compile(r"^\s*([^\W\d_]\w*)\s*:\s*(.*?)\s*$", re.DOTALL)
_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')

_TAG_KINDS = {
    "voz": "voice",
    "voice": "voice",
    "pausa": "pause",
    "pause": "pause",
    "musica": "music",
    "música": "music",
    "music": "music",
    "sfx": "sfx",
    "titulo": "title",
    "título": "title",
    "title": "title",
}

_BG_FLAGS = {"fondo", "bg", "background"}
_TRUE = {"1", "true", "yes", "si", "sí", "on"}
_FALSE = {"0", "false", "no", "off"}


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def _tokens(arg: str) -> list[str]:
    return [_unquote(t) for t in _TOKEN_RE.findall(arg)]


def _split_attrs(tokens: list[str], line: int, tag: str) -> tuple[dict[str, str], set[str]]:
    attrs: dict[str, str] = {}
    flags: set[str] = set()
    for tok in tokens:
        if "=" in tok:
            key, value = tok.split("=", 1)
            key = key.strip().lower()
            if not key:
                raise ScriptParseError(f"atributo vacío en [{tag}:...]", line)
            attrs[key] = _unquote(value.strip())
        else:
            flags.add(tok.lower())
    return attrs, flags


def _float_attr(value: str, name: str, line: int, *, lo: float | None = None,
                hi: float | None = None) -> float:
    try:
        num = float(value.replace(",", "."))
    except ValueError as exc:
        raise ScriptParseError(f"'{name}' debe ser un número (recibido {value!r})", line) from exc
    if lo is not None and num < lo:
        raise ScriptParseError(f"'{name}' debe ser >= {lo} (recibido {num})", line)
    if hi is not None and num > hi:
        raise ScriptParseError(f"'{name}' debe ser <= {hi} (recibido {num})", line)
    return num


def _bool_attr(value: str, name: str, line: int) -> bool:
    low = value.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ScriptParseError(f"'{name}' debe ser true/false (recibido {value!r})", line)


def _check_unknown(attrs: dict[str, str], flags: set[str], allowed: set[str],
                   allowed_flags: set[str], tag: str, line: int) -> None:
    bad = sorted(set(attrs) - allowed) + sorted(flags - allowed_flags)
    if bad:
        raise ScriptParseError(
            f"atributo(s) desconocido(s) en [{tag}:...]: {', '.join(bad)}", line
        )


@dataclass
class _VoiceState:
    voice: str | None = None
    lang: str | None = None
    speed: float | None = None
    engine: str | None = None


class _Parser:
    def __init__(self, max_chars: int, paragraph_pause: float | None) -> None:
        self.max_chars = max_chars
        self.paragraph_pause_arg = paragraph_pause
        self.meta = ScriptMeta()
        self.segments: list[Segment] = []
        self.state = _VoiceState()
        self.buffer: list[str] = []
        self.buffer_line: int | None = None
        self.pending_paragraph = False

    # -- helpers ---------------------------------------------------------
    @property
    def paragraph_pause(self) -> float:
        if self.paragraph_pause_arg is not None:
            return self.paragraph_pause_arg
        if self.meta.paragraph_pause is not None:
            return self.meta.paragraph_pause
        return DEFAULT_PARAGRAPH_PAUSE

    def add_text(self, text: str, line: int) -> None:
        text = text.strip()
        if not text:
            return
        if self.buffer_line is None:
            self.buffer_line = line
        if self.buffer and not self.buffer[-1].endswith("\n"):
            self.buffer.append(" ")
        self.buffer.append(text)

    def end_line(self) -> None:
        if self.buffer and not self.buffer[-1].endswith("\n"):
            self.buffer.append("\n")

    def flush(self) -> None:
        text = "".join(self.buffer).strip()
        line = self.buffer_line
        self.buffer = []
        self.buffer_line = None
        if not text:
            return
        voice = self.state.voice or self.meta.default_voice
        if not voice:
            raise ScriptParseError(
                "hay texto sin voz asignada: usa [voz:nombre] antes o define "
                "'default_voice' en el front matter",
                line,
            )
        if self.pending_paragraph and self.segments and isinstance(self.segments[-1], Speech):
            pause = self.paragraph_pause
            if pause > 0:
                self.segments.append(Pause(seconds=pause, line=line))
        self.pending_paragraph = False
        for chunk in chunk_text(text, self.max_chars):
            self.segments.append(
                Speech(
                    voice=voice,
                    text=chunk,
                    lang=self.state.lang,
                    speed=self.state.speed,
                    engine=self.state.engine,
                    line=line,
                )
            )

    def emit(self, seg: Segment) -> None:
        self.flush()
        self.pending_paragraph = False
        self.segments.append(seg)

    # -- tags ------------------------------------------------------------
    def handle_tag(self, content: str, line: int) -> None:
        head = _TAG_HEAD_RE.match(content)
        if not head:
            raise ScriptParseError(
                f"etiqueta no reconocida '[{content}]' (formato esperado [tipo:valor])", line
            )
        raw_kind, arg = head.group(1), head.group(2)
        kind = _TAG_KINDS.get(raw_kind.lower())
        if kind is None:
            raise ScriptParseError(
                f"etiqueta desconocida '[{raw_kind}:...]' (válidas: voz/voice, pausa/pause, "
                "musica/music, sfx, titulo/title)",
                line,
            )
        if kind == "title":
            self.meta.title = arg.strip()
            return
        tokens = _tokens(arg)
        if not tokens:
            raise ScriptParseError(f"la etiqueta [{raw_kind}:] necesita un valor", line)
        getattr(self, f"_tag_{kind}")(tokens, raw_kind, line)

    def _tag_voice(self, tokens: list[str], tag: str, line: int) -> None:
        self.flush()
        attrs, flags = _split_attrs(tokens[1:], line, tag)
        _check_unknown(attrs, flags, {"lang", "speed", "engine"}, set(), tag, line)
        state = _VoiceState(voice=tokens[0])
        if "lang" in attrs:
            state.lang = attrs["lang"]
        if "speed" in attrs:
            state.speed = _float_attr(attrs["speed"], "speed", line, lo=0.25, hi=4.0)
        if "engine" in attrs:
            engine = attrs["engine"].lower()
            valid = known_engines()
            if engine not in valid:
                raise ScriptParseError(
                    f"motor desconocido '{engine}' (válidos: {', '.join(valid)})", line
                )
            state.engine = engine
        self.state = state

    def _tag_pause(self, tokens: list[str], tag: str, line: int) -> None:
        if len(tokens) != 1:
            raise ScriptParseError(f"[{tag}:...] solo admite un número de segundos", line)
        seconds = _float_attr(tokens[0].rstrip("sS"), "pausa", line, lo=0.0)
        self.emit(Pause(seconds=seconds, line=line))

    def _tag_music(self, tokens: list[str], tag: str, line: int) -> None:
        path = tokens[0]
        attrs, flags = _split_attrs(tokens[1:], line, tag)
        if path.lower() in ("stop", "fin", "parar"):
            _check_unknown(attrs, flags, {"fade"}, set(), tag, line)
            fade = _float_attr(attrs.get("fade", str(DEFAULT_BG_FADE)), "fade", line, lo=0.0)
            self.emit(Music(path="", fade=fade, stop=True, line=line))
            return
        _check_unknown(attrs, flags, {"vol", "volume", "fade", "bg", "fondo", "background"},
                       _BG_FLAGS, tag, line)
        background = bool(flags & _BG_FLAGS)
        for key in ("bg", "fondo", "background"):
            if key in attrs:
                background = _bool_attr(attrs[key], key, line)
        vol_raw = attrs.get("vol", attrs.get("volume"))
        default_vol = DEFAULT_BG_VOLUME if background else DEFAULT_MUSIC_VOLUME
        volume = (default_vol if vol_raw is None
                  else _float_attr(vol_raw, "vol", line, lo=0.0, hi=1.0))
        default_fade = DEFAULT_BG_FADE if background else 0.0
        fade = _float_attr(attrs.get("fade", str(default_fade)), "fade", line, lo=0.0)
        self.emit(Music(path=path, volume=volume, fade=fade, background=background, line=line))

    def _tag_sfx(self, tokens: list[str], tag: str, line: int) -> None:
        attrs, flags = _split_attrs(tokens[1:], line, tag)
        _check_unknown(attrs, flags, {"vol", "volume"}, set(), tag, line)
        vol_raw = attrs.get("vol", attrs.get("volume"))
        volume = (DEFAULT_SFX_VOLUME if vol_raw is None
                  else _float_attr(vol_raw, "vol", line, lo=0.0, hi=1.0))
        self.emit(Sfx(path=tokens[0], volume=volume, line=line))

    # -- bucle principal -------------------------------------------------
    def parse(self, text: str) -> ParsedScript:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[0].startswith("﻿"):
            lines[0] = lines[0][1:]
        start = 0
        if lines and lines[0].strip() == "---":
            try:
                end = next(i for i in range(1, len(lines)) if lines[i].strip() in ("---", "..."))
            except StopIteration:
                raise ScriptParseError("front matter sin cerrar (falta '---')", 1) from None
            data = _parse_front_matter("\n".join(lines[1:end]), 2)
            self.meta = _build_meta(data, 1)
            start = end + 1

        for idx in range(start, len(lines)):
            lineno = idx + 1
            raw = lines[idx]
            stripped = raw.strip()
            if not stripped:
                if self.buffer:
                    self.flush()
                self.pending_paragraph = True
                continue
            if stripped.startswith("#") or stripped.startswith("<!--"):
                continue
            pos = 0
            for m in _TAG_RE.finditer(raw):
                self.add_text(raw[pos:m.start()], lineno)
                self.handle_tag(m.group(1), lineno)
                pos = m.end()
            self.add_text(raw[pos:], lineno)
            self.end_line()
        self.flush()
        return ParsedScript(meta=self.meta, segments=self.segments)


def parse_script(text: str, *, max_chars: int = DEFAULT_MAX_CHARS,
                 paragraph_pause: float | None = None) -> ParsedScript:
    """Parsea el texto de un guion.

    :param max_chars: longitud máxima de cada trozo de texto (~250 para F5-TTS).
    :param paragraph_pause: pausa automática entre párrafos; ``None`` = la del
        front matter (``paragraph_pause``) o 0.4 s.
    :raises ScriptParseError: con número de línea si hay etiquetas inválidas.
    """
    return _Parser(max_chars, paragraph_pause).parse(text)


def parse_file(path: str | Path, *, max_chars: int = DEFAULT_MAX_CHARS,
               paragraph_pause: float | None = None) -> ParsedScript:
    """Lee (UTF-8) y parsea un fichero de guion."""
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_script(text, max_chars=max_chars, paragraph_pause=paragraph_pause)
