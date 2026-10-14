"""On-disk voice registry.

Layout of each voice::

    voices/<name>/
        ref.wav     reference clip (mono, 24 kHz, 16 bit, 5-15 s)
        ref.txt     exact transcript of the clip (required by F5-TTS)
        voice.json  {name, lang, engine, description, xtts_speaker, speed,
                     provider_voice_id, provider_options}

Voices for cloud engines (ElevenLabs, Azure, OpenAI...) do not need
``ref.wav``: they use ``provider_voice_id`` (ID or name of the voice at the provider) and,
optionally, ``provider_options`` (dict with provider-specific options).

The default directory is ``<project>/voices``; it can be changed with the
``PODCAST_TTS_VOICES_DIR`` environment variable or by passing ``voices_dir``.
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
# Windows reserved device names (not valid as folder names).
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# XTTS v2 built-in speakers (58, in the order of ``TTS(...).speakers``; see docs/ENGINES.md).
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
    """Generic voice registry error."""


class VoiceNotFoundError(VoiceError, KeyError):
    """The requested voice does not exist."""

    def __str__(self) -> str:  # KeyError adds quotes; strip them
        return str(self.args[0]) if self.args else "voice not found"


@dataclass
class Voice:
    """Registered voice (or ephemeral, if ``path`` does not exist)."""

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
        """Transcript of the reference clip ('' if missing)."""
        try:
            return self.ref_txt.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def fingerprint(self) -> str:
        """Fingerprint that changes when the clip or the configuration changes (for caches)."""
        parts = [self.name, self.engine, self.xtts_speaker or "", self.ref_text]
        if self.has_ref:
            st = self.ref_wav.stat()
            parts += [str(st.st_size), str(int(st.st_mtime))]
        # Only if present, so the cache of already generated local voices is not invalidated.
        if self.provider_voice_id or self.provider_options:
            parts += [
                self.provider_voice_id or "",
                json.dumps(self.provider_options, sort_keys=True, ensure_ascii=False, default=str),
            ]
        return "|".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Contents of voice.json."""
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
        """Load a voice from its directory (voice.json is optional).

        Raises :class:`VoiceError` if ``voice.json`` is not valid JSON, is not an
        object or has values of the wrong type.
        """
        data: dict[str, Any] = {}
        cfg = path / "voice.json"
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise VoiceError(f"invalid voice.json in {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise VoiceError(
                    f"invalid voice.json in {path}: it must be a JSON object "
                    f"({{...}}), not {type(data).__name__}"
                )
        known = {"name", "lang", "engine", "description", "xtts_speaker", "speed",
                 "provider_voice_id", "provider_options"}
        options = data.get("provider_options") or {}
        if not isinstance(options, dict):
            raise VoiceError(f"'provider_options' must be a JSON object in {cfg}")
        speaker = data.get("xtts_speaker") or None
        if speaker is not None and not isinstance(speaker, str):
            raise VoiceError(f"'xtts_speaker' must be a string in {cfg}")
        raw_speed = data.get("speed") or 1.0
        try:
            if isinstance(raw_speed, bool):
                raise TypeError("boolean")
            speed = float(raw_speed)
        except (TypeError, ValueError) as exc:
            raise VoiceError(
                f"'speed' must be a number in {cfg} (value: {raw_speed!r})"
            ) from exc
        if not math.isfinite(speed) or speed <= 0:
            raise VoiceError(f"'speed' must be a positive number in {cfg}")
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
            raise VoiceError(f"invalid voice.json in {path}: {exc}") from exc


def default_voices_dir() -> Path:
    """Voices directory: ``$PODCAST_TTS_VOICES_DIR`` or ``<project>/voices``."""
    env = os.environ.get("PODCAST_TTS_VOICES_DIR")
    return Path(env) if env else PROJECT_ROOT / "voices"


def voice_engines() -> tuple[str, ...]:
    """Valid engines for a voice (built-in + plugins; see :mod:`podcast_tts.engines`)."""
    from .engines import engine_names

    return engine_names()


def __getattr__(attr: str) -> Any:  # PEP 562: dynamic VOICE_ENGINES (compatibility)
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
            f"invalid voice name {name!r}: use letters, digits, '_' or '-' (no spaces)"
        )
    if name.upper() in _RESERVED_NAMES:
        raise VoiceError(
            f"invalid voice name {name!r}: it is a reserved Windows name "
            "(CON, PRN, AUX, NUL, COM1-9, LPT1-9)"
        )


def _voice_path(root: Path, name: str) -> Path:
    """Path of voice ``name`` inside ``root``; never escapes ``root``."""
    _validate_name(name)
    path = root / name
    try:
        inside = path.resolve().is_relative_to(root.resolve())
    except OSError:
        inside = False
    if not inside:
        raise VoiceError(f"invalid voice name {name!r}: it escapes the voices directory")
    return path


def list_voices(voices_dir: str | Path | None = None) -> list[Voice]:
    """List the voices (subdirectories with ``voice.json`` or ``ref.wav``), sorted by name."""
    root = _dir(voices_dir)
    if not root.is_dir():
        return []
    voices = []
    for sub in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if sub.is_dir() and ((sub / "voice.json").is_file() or (sub / "ref.wav").is_file()):
            try:
                voices.append(Voice.from_dir(sub))
            except VoiceError as exc:
                warnings.warn(f"skipping voice '{sub.name}': {exc}", stacklevel=2)
    return voices


def get_voice(name: str, voices_dir: str | Path | None = None) -> Voice:
    """Return voice ``name``; raises :class:`VoiceNotFoundError` if it does not exist."""
    root = _dir(voices_dir)
    try:
        path = _voice_path(root, name)
    except VoiceError as exc:
        raise VoiceNotFoundError(f"voice '{name}' does not exist: {exc}") from exc
    if not path.is_dir() or not ((path / "voice.json").is_file() or (path / "ref.wav").is_file()):
        available = ", ".join(v.name for v in list_voices(root)) or "(none)"
        raise VoiceNotFoundError(
            f"voice '{name}' does not exist in {root}. Available: {available}"
        )
    return Voice.from_dir(path)


def _convert_reference(src: Path, dst: Path, max_seconds: float) -> float:
    """Convert ``src`` to mono 24 kHz 16-bit WAV (max ``max_seconds``). Returns the duration."""
    from pydub import AudioSegment

    if src.suffix.lower() != ".wav" and not (
        shutil.which(str(getattr(AudioSegment, "converter", "") or "ffmpeg"))
        or shutil.which("ffmpeg")
    ):
        raise VoiceError(
            f"ffmpeg not found; it is needed to read '{src.name}'. Install it with "
            "`winget install Gyan.FFmpeg` (and open a new console) or use a .wav clip."
        )
    try:
        audio = AudioSegment.from_file(str(src))
    except Exception as exc:  # pydub raises CouldntDecodeError, FileNotFoundError...
        raise VoiceError(f"could not read the audio {src}: {exc}") from exc
    audio = audio.set_channels(1).set_frame_rate(REF_SAMPLE_RATE).set_sample_width(2)
    original = len(audio) / 1000.0
    if original > max_seconds:
        audio = audio[: int(max_seconds * 1000)].fade_out(50)
        warnings.warn(
            f"the clip is {original:.1f} s long; it has been trimmed to {max_seconds:.0f} s. "
            "Make sure the transcript only covers the part that was kept.",
            stacklevel=3,
        )
    duration = len(audio) / 1000.0
    if duration < MIN_REF_SECONDS:
        warnings.warn(
            f"the clip is only {duration:.1f} s long; 5-15 s is recommended for good cloning.",
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
    """Create (or overwrite) a voice.

    ``wav_path`` can be any format ffmpeg reads; it is converted to mono
    24 kHz 16 bit and trimmed to ``max_seconds``. It can be ``None`` when using a
    built-in ``xtts_speaker`` or when the voice belongs to a cloud engine (``engine``
    ``elevenlabs``, ``azure``, ``openai``...), which needs ``provider_voice_id``.
    F5-TTS needs ``transcript``.
    """
    _validate_name(name)
    engine = (engine or "").lower()
    valid = voice_engines()
    if engine not in valid:
        raise VoiceError(f"unknown engine '{engine}' (valid: {', '.join(valid)})")
    provider_voice_id = (provider_voice_id or "").strip() or None
    if provider_options is not None and not isinstance(provider_options, dict):
        raise VoiceError("provider_options must be a dictionary")
    cloud = _engine_kind(engine) == "cloud"
    if cloud and not provider_voice_id:
        raise VoiceError(
            f"engine '{engine}' is a cloud engine: the provider's voice ID is required "
            "(provider_voice_id / --provider-voice-id)"
        )
    if wav_path is None and not xtts_speaker and not cloud:
        raise VoiceError("a reference clip (wav_path) or an xtts_speaker is required")
    if wav_path is not None and not Path(wav_path).is_file():
        raise VoiceError(f"audio file {wav_path} does not exist")
    if engine == "f5" and wav_path is not None and not transcript.strip():
        warnings.warn("F5-TTS needs the transcript of the clip (ref.txt).", stacklevel=2)

    root = _dir(voices_dir)
    path = _voice_path(root, name)
    if path.exists():
        if not overwrite:
            raise VoiceError(f"voice '{name}' already exists (use overwrite=True / --overwrite)")
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
    """Delete the directory of voice ``name``."""
    _validate_name(name)
    voice = get_voice(name, voices_dir)
    shutil.rmtree(voice.path)


def list_xtts_speakers() -> list[str]:
    """Names of the XTTS v2 built-in speakers (without loading the model)."""
    return list(XTTS_BUILTIN_SPEAKERS)
