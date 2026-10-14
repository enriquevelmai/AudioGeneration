"""Registro de voces en disco.

Estructura de cada voz::

    voices/<nombre>/
        ref.wav     clip de referencia (mono, 24 kHz, 16 bit, 5-15 s)
        ref.txt     transcripción exacta del clip (necesaria para F5-TTS)
        voice.json  {name, lang, engine, description, xtts_speaker, speed,
                     provider_voice_id, provider_options}

Las voces de motores en la nube (ElevenLabs, Azure, OpenAI...) no necesitan
``ref.wav``: usan ``provider_voice_id`` (ID o nombre de la voz en el proveedor) y,
opcionalmente, ``provider_options`` (dict con opciones propias del proveedor).

El directorio por defecto es ``<proyecto>/voices``; se puede cambiar con la
variable de entorno ``PODCAST_TTS_VOICES_DIR`` o pasando ``voices_dir``.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MAX_REF_SECONDS",
    "MIN_REF_SECONDS",
    "REF_SAMPLE_RATE",
    "Voice",
    "VoiceError",
    "VoiceNotFoundError",
    "XTTS_BUILTIN_SPEAKERS",
    "add_voice",
    "default_voices_dir",
    "get_voice",
    "list_voices",
    "list_xtts_speakers",
    "remove_voice",
    "voice_engines",
]

REF_SAMPLE_RATE = 24000
MAX_REF_SECONDS = 15.0
MIN_REF_SECONDS = 3.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
# Nombres de dispositivo reservados de Windows (no valen como carpeta).
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Speakers integrados de XTTS v2 (58, en el orden de ``TTS(...).speakers``; ver docs/ENGINES.md).
XTTS_BUILTIN_SPEAKERS: tuple[str, ...] = (
    "Claribel Dervla",
    "Daisy Studious",
    "Gracie Wise",
    "Tammie Ema",
    "Alison Dietlinde",
    "Ana Florence",
    "Annmarie Nele",
    "Asya Anara",
    "Brenda Stern",
    "Gitta Nikolina",
    "Henriette Usha",
    "Sofia Hellen",
    "Tammy Grit",
    "Tanja Adelina",
    "Vjollca Johnnie",
    "Andrew Chipper",
    "Badr Odhiambo",
    "Dionisio Schuyler",
    "Royston Min",
    "Viktor Eka",
    "Abrahan Mack",
    "Adde Michal",
    "Baldur Sanjin",
    "Craig Gutsy",
    "Damien Black",
    "Gilberto Mathias",
    "Ilkin Urbano",
    "Kazuhiko Atallah",
    "Ludvig Milivoj",
    "Suad Qasim",
    "Torcull Diarmuid",
    "Viktor Menelaos",
    "Zacharie Aimilios",
    "Nova Hogarth",
    "Maja Ruoho",
    "Uta Obando",
    "Lidiya Szekeres",
    "Chandra MacFarland",
    "Szofi Granger",
    "Camilla Holmström",
    "Lilya Stainthorpe",
    "Zofija Kendrick",
    "Narelle Moon",
    "Barbora MacLean",
    "Alexandra Hisakawa",
    "Alma María",
    "Rosemary Okafor",
    "Ige Behringer",
    "Filip Traverse",
    "Damjan Chapman",
    "Wulf Carlevaro",
    "Aaron Dreschner",
    "Kumar Dahl",
    "Eugenio Mataracı",
    "Ferran Simen",
    "Xavier Hayasaka",
    "Luis Moray",
    "Marcos Rudaski",
)


class VoiceError(Exception):
    """Error genérico del registro de voces."""


class VoiceNotFoundError(VoiceError, KeyError):
    """La voz pedida no existe."""

    def __str__(self) -> str:  # KeyError añade comillas; las quitamos
        return str(self.args[0]) if self.args else "voz no encontrada"


@dataclass
class Voice:
    """Voz registrada (o efímera, si ``path`` no existe)."""

    name: str
    path: Path
    lang: str = "es"
    engine: str = "f5"
    description: str = ""
    xtts_speaker: str | None = None
    speed: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)
    provider_voice_id: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)

    @property
    def ref_wav(self) -> Path:
        return self.path / "ref.wav"

    @property
    def ref_txt(self) -> Path:
        return self.path / "ref.txt"

    @property
    def has_ref(self) -> bool:
        return self.ref_wav.is_file()

    @property
    def ref_text(self) -> str:
        """Transcripción del clip de referencia ('' si no existe)."""
        try:
            return self.ref_txt.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def fingerprint(self) -> str:
        """Huella que cambia si cambia el clip o la configuración (para cachés)."""
        parts = [self.name, self.engine, self.xtts_speaker or "", self.ref_text]
        if self.has_ref:
            st = self.ref_wav.stat()
            parts += [str(st.st_size), str(int(st.st_mtime))]
        # Solo si existen, para no invalidar la caché de las voces locales ya generadas.
        if self.provider_voice_id or self.provider_options:
            parts += [
                self.provider_voice_id or "",
                json.dumps(self.provider_options, sort_keys=True, ensure_ascii=False, default=str),
            ]
        return "|".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Contenido de voice.json."""
        data: dict[str, Any] = {
            "name": self.name,
            "lang": self.lang,
            "engine": self.engine,
            "description": self.description,
            "xtts_speaker": self.xtts_speaker,
            "speed": self.speed,
        }
        if self.provider_voice_id:
            data["provider_voice_id"] = self.provider_voice_id
        if self.provider_options:
            data["provider_options"] = dict(self.provider_options)
        data.update(self.extra)
        return data

    @classmethod
    def from_dir(cls, path: Path) -> "Voice":
        """Carga una voz desde su directorio (voice.json opcional).

        Lanza :class:`VoiceError` si ``voice.json`` no es JSON válido, no es un
        objeto o tiene valores de tipo incorrecto.
        """
        data: dict[str, Any] = {}
        cfg = path / "voice.json"
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise VoiceError(f"voice.json inválido en {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise VoiceError(
                    f"voice.json inválido en {path}: debe ser un objeto JSON "
                    f"({{...}}), no {type(data).__name__}"
                )
        known = {"name", "lang", "engine", "description", "xtts_speaker", "speed",
                 "provider_voice_id", "provider_options"}
        options = data.get("provider_options") or {}
        if not isinstance(options, dict):
            raise VoiceError(f"'provider_options' debe ser un objeto JSON en {cfg}")
        speaker = data.get("xtts_speaker") or None
        if speaker is not None and not isinstance(speaker, str):
            raise VoiceError(f"'xtts_speaker' debe ser un texto en {cfg}")
        raw_speed = data.get("speed") or 1.0
        try:
            if isinstance(raw_speed, bool):
                raise TypeError("booleano")
            speed = float(raw_speed)
        except (TypeError, ValueError) as exc:
            raise VoiceError(
                f"'speed' debe ser un número en {cfg} (valor: {raw_speed!r})"
            ) from exc
        if not math.isfinite(speed) or speed <= 0:
            raise VoiceError(f"'speed' debe ser un número positivo en {cfg}")
        try:
            return cls(
                name=path.name,
                path=path,
                lang=str(data.get("lang") or "es"),
                engine=str(data.get("engine") or "f5").lower(),
                description=str(data.get("description") or ""),
                xtts_speaker=speaker,
                speed=speed,
                extra={k: v for k, v in data.items() if k not in known},
                provider_voice_id=str(data.get("provider_voice_id") or "").strip() or None,
                provider_options=dict(options),
            )
        except (TypeError, ValueError) as exc:
            raise VoiceError(f"voice.json inválido en {path}: {exc}") from exc


def default_voices_dir() -> Path:
    """Directorio de voces: ``$PODCAST_TTS_VOICES_DIR`` o ``<proyecto>/voices``."""
    env = os.environ.get("PODCAST_TTS_VOICES_DIR")
    return Path(env) if env else PROJECT_ROOT / "voices"


def voice_engines() -> tuple[str, ...]:
    """Motores válidos para una voz (integrados + plugins; ver :mod:`podcast_tts.engines`)."""
    from .engines import engine_names

    return engine_names()


def __getattr__(attr: str) -> Any:  # PEP 562: VOICE_ENGINES dinámico (compatibilidad)
    if attr == "VOICE_ENGINES":
        return voice_engines()
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


def _engine_kind(engine: str) -> str:
    from .engines import EngineError, engine_kind

    try:
        return engine_kind(engine)
    except EngineError:
        return "local"


def _dir(voices_dir: str | Path | None) -> Path:
    return Path(voices_dir) if voices_dir is not None else default_voices_dir()


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise VoiceError(
            f"nombre de voz inválido {name!r}: usa letras, números, '_' o '-' (sin espacios)"
        )
    if name.upper() in _RESERVED_NAMES:
        raise VoiceError(
            f"nombre de voz inválido {name!r}: es un nombre reservado de Windows "
            "(CON, PRN, AUX, NUL, COM1-9, LPT1-9)"
        )


def _voice_path(root: Path, name: str) -> Path:
    """Ruta de la voz ``name`` dentro de ``root``; nunca sale de ``root``."""
    _validate_name(name)
    path = root / name
    try:
        inside = path.resolve().is_relative_to(root.resolve())
    except OSError:
        inside = False
    if not inside:
        raise VoiceError(f"nombre de voz inválido {name!r}: sale del directorio de voces")
    return path


def list_voices(voices_dir: str | Path | None = None) -> list[Voice]:
    """Lista las voces (subdirectorios con ``voice.json`` o ``ref.wav``), ordenadas por nombre."""
    root = _dir(voices_dir)
    if not root.is_dir():
        return []
    voices = []
    for sub in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if sub.is_dir() and ((sub / "voice.json").is_file() or (sub / "ref.wav").is_file()):
            try:
                voices.append(Voice.from_dir(sub))
            except VoiceError as exc:
                warnings.warn(f"se omite la voz '{sub.name}': {exc}", stacklevel=2)
    return voices


def get_voice(name: str, voices_dir: str | Path | None = None) -> Voice:
    """Devuelve la voz ``name``; lanza :class:`VoiceNotFoundError` si no existe."""
    root = _dir(voices_dir)
    try:
        path = _voice_path(root, name)
    except VoiceError as exc:
        raise VoiceNotFoundError(f"la voz '{name}' no existe: {exc}") from exc
    if not path.is_dir() or not ((path / "voice.json").is_file() or (path / "ref.wav").is_file()):
        available = ", ".join(v.name for v in list_voices(root)) or "(ninguna)"
        raise VoiceNotFoundError(
            f"la voz '{name}' no existe en {root}. Disponibles: {available}"
        )
    return Voice.from_dir(path)


def _convert_reference(src: Path, dst: Path, max_seconds: float) -> float:
    """Convierte ``src`` a WAV mono 24 kHz 16 bit (máx ``max_seconds``). Devuelve la duración."""
    from pydub import AudioSegment

    try:
        audio = AudioSegment.from_file(str(src))
    except Exception as exc:  # pydub lanza CouldntDecodeError, FileNotFoundError...
        raise VoiceError(f"no se pudo leer el audio {src}: {exc}") from exc
    audio = audio.set_channels(1).set_frame_rate(REF_SAMPLE_RATE).set_sample_width(2)
    original = len(audio) / 1000.0
    if original > max_seconds:
        audio = audio[: int(max_seconds * 1000)].fade_out(50)
        warnings.warn(
            f"el clip dura {original:.1f} s; se ha recortado a {max_seconds:.0f} s. "
            "Asegúrate de que la transcripción corresponde solo a la parte conservada.",
            stacklevel=3,
        )
    duration = len(audio) / 1000.0
    if duration < MIN_REF_SECONDS:
        warnings.warn(
            f"el clip dura solo {duration:.1f} s; se recomiendan 5-15 s para clonar bien.",
            stacklevel=3,
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(dst), format="wav").close()
    return duration


def add_voice(
    name: str,
    wav_path: str | Path | None,
    transcript: str = "",
    lang: str = "es",
    engine: str = "f5",
    description: str = "",
    xtts_speaker: str | None = None,
    speed: float = 1.0,
    *,
    voices_dir: str | Path | None = None,
    overwrite: bool = False,
    max_seconds: float = MAX_REF_SECONDS,
    provider_voice_id: str | None = None,
    provider_options: dict[str, Any] | None = None,
) -> Voice:
    """Crea (o sobrescribe) una voz.

    ``wav_path`` puede ser cualquier formato que lea ffmpeg; se convierte a mono
    24 kHz 16 bit y se recorta a ``max_seconds``. Puede ser ``None`` si se usa un
    ``xtts_speaker`` integrado o si la voz es de un motor en la nube (``engine``
    ``elevenlabs``, ``azure``, ``openai``...), que necesita ``provider_voice_id``.
    F5-TTS necesita ``transcript``.
    """
    _validate_name(name)
    engine = (engine or "").lower()
    valid = voice_engines()
    if engine not in valid:
        raise VoiceError(f"motor desconocido '{engine}' (válidos: {', '.join(valid)})")
    provider_voice_id = (provider_voice_id or "").strip() or None
    if provider_options is not None and not isinstance(provider_options, dict):
        raise VoiceError("provider_options debe ser un diccionario")
    cloud = _engine_kind(engine) == "cloud"
    if cloud and not provider_voice_id:
        raise VoiceError(
            f"el motor '{engine}' es en la nube: hace falta el ID de voz del proveedor "
            "(provider_voice_id / --provider-voice-id)"
        )
    if wav_path is None and not xtts_speaker and not cloud:
        raise VoiceError("hace falta un clip de referencia (wav_path) o un xtts_speaker")
    if wav_path is not None and not Path(wav_path).is_file():
        raise VoiceError(f"no existe el fichero de audio {wav_path}")
    if engine == "f5" and wav_path is not None and not transcript.strip():
        warnings.warn("F5-TTS necesita la transcripción del clip (ref.txt).", stacklevel=2)

    root = _dir(voices_dir)
    path = _voice_path(root, name)
    if path.exists():
        if not overwrite:
            raise VoiceError(f"la voz '{name}' ya existe (usa overwrite=True / --overwrite)")
    path.mkdir(parents=True, exist_ok=True)

    if wav_path is not None:
        src = Path(wav_path).resolve()
        dst = path / "ref.wav"
        if src == dst.resolve():
            tmp = path / "_ref_src.wav"
            shutil.copyfile(src, tmp)
            src = tmp
        _convert_reference(src, dst, max_seconds)
        if src.name == "_ref_src.wav":
            src.unlink(missing_ok=True)
    if wav_path is not None or not cloud or transcript.strip():
        (path / "ref.txt").write_text(transcript.strip() + "\n", encoding="utf-8")

    voice = Voice(
        name=name,
        path=path,
        lang=lang,
        engine=engine,
        description=description,
        xtts_speaker=xtts_speaker or None,
        speed=float(speed),
        provider_voice_id=provider_voice_id,
        provider_options=dict(provider_options or {}),
    )
    (path / "voice.json").write_text(
        json.dumps(voice.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return voice


def remove_voice(name: str, voices_dir: str | Path | None = None) -> None:
    """Elimina el directorio de la voz ``name``."""
    _validate_name(name)
    voice = get_voice(name, voices_dir)
    shutil.rmtree(voice.path)


def list_xtts_speakers() -> list[str]:
    """Nombres de los speakers integrados de XTTS v2 (sin cargar el modelo)."""
    return list(XTTS_BUILTIN_SPEAKERS)
