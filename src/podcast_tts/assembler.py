"""Ensamblado del episodio: síntesis (con caché), pausas, música, sfx, mezcla y exportación.

Flujo: ``ParsedScript`` -> línea temporal en numpy (float32 mono) ->
música de fondo con *ducking* -> normalización (~-16 LUFS) ->
``pydub.AudioSegment`` -> MP3/WAV con ffmpeg.

Prioridad de parámetros de cada frase:

- motor: ``engine_override`` (CLI) > etiqueta ``engine=`` > front matter
  ``engine`` > ``voice.json`` > ``AssembleOptions.default_engine``.
- idioma: etiqueta ``lang=`` > front matter ``lang`` > ``voice.json`` >
  ``AssembleOptions.default_lang``.
- velocidad: etiqueta ``speed=`` > ``voice.json`` > 1.0.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .engines import TTSEngine, get_engine
from .engines.base import engine_cache_tag
from .script_parser import Music, ParsedScript, Pause, Segment, Sfx, Speech, parse_file
from .voices import PROJECT_ROOT, Voice, VoiceNotFoundError, default_voices_dir, get_voice

__all__ = [
    "AssembleError",
    "AssembleOptions",
    "EngineResolver",
    "ProgressCallback",
    "ResolvedSpeech",
    "SynthesisCache",
    "assemble",
    "export_audio",
    "ffmpeg_available",
    "generate",
    "normalize_loudness",
    "render",
    "resolve_speech",
    "synthesize_speech",
]

ProgressCallback = Callable[[int, int, str], None]
"""``progress(i, n, mensaje)``: segmento ``i`` (1-based) de ``n``."""

EngineResolver = Callable[[str], TTSEngine]
"""Función ``nombre_motor -> instancia``. Por defecto :func:`engines.get_engine`."""

DEFAULT_CACHE_DIR = PROJECT_ROOT / ".cache" / "tts"
MAX_EPISODE_SECONDS = 24 * 3600  # tope de seguridad de la línea temporal


class AssembleError(RuntimeError):
    """Error al montar el episodio (fichero de música inexistente, voz no encontrada...)."""


@dataclass
class AssembleOptions:
    """Opciones de montaje."""

    sample_rate: int = 44100
    default_engine: str = "f5"
    engine_override: str | None = None
    default_lang: str = "es"
    target_lufs: float | None = -16.0  # None = no normalizar
    peak_dbfs: float = -1.0
    chunk_gap: float = 0.12  # silencio entre trozos consecutivos de texto
    cache_dir: Path | None = field(default_factory=lambda: DEFAULT_CACHE_DIR)  # None = sin caché
    base_dir: Path | None = None  # para rutas relativas de música/sfx
    duck_ramp: float = 0.3  # duración de las rampas de ducking (s)
    duck_min_gap: float = 1.0  # huecos sin voz más cortos no suben la música
    bg_full_ratio: float = 2.5  # volumen sin voz = min(1, vol * ratio)
    # False (UI remota): música/sfx solo con rutas relativas dentro de base_dir o del
    # proyecto; se rechazan las absolutas y las que contienen '..'.
    allow_external_paths: bool = True


@dataclass
class ResolvedSpeech:
    """Parámetros efectivos de una frase."""

    voice: Voice
    engine: str
    lang: str
    speed: float


# --------------------------------------------------------------------------- #
# Utilidades de audio
# --------------------------------------------------------------------------- #


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x.astype(np.float32, copy=False)
    try:
        from scipy.signal import resample_poly  # type: ignore[import-untyped]

        g = math.gcd(sr_in, sr_out)
        return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)
    except ImportError:
        n_out = int(round(x.size * sr_out / sr_in))
        t_out = np.arange(n_out) * (sr_in / sr_out)
        return np.interp(t_out, np.arange(x.size), x).astype(np.float32)


def _to_mono_float(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x)
    if x.ndim == 2:
        # (n, canales) o (canales, n)
        x = x.mean(axis=1) if x.shape[0] >= x.shape[1] else x.mean(axis=0)
    if np.issubdtype(x.dtype, np.integer):
        x = x.astype(np.float32) / float(np.iinfo(x.dtype).max)
    return np.nan_to_num(x.astype(np.float32, copy=False))


def _segment_to_array(audio: "AudioSegment", sr: int) -> np.ndarray:  # noqa: F821
    audio = audio.set_channels(1).set_frame_rate(sr)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
    return samples / float(1 << (8 * audio.sample_width - 1))


def _array_to_segment(x: np.ndarray, sr: int) -> "AudioSegment":  # noqa: F821
    from pydub import AudioSegment

    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    return AudioSegment(pcm.tobytes(), frame_rate=sr, sample_width=2, channels=1)


FFMPEG_HINT = (
    "Instálalo con `winget install Gyan.FFmpeg` (y abre una consola nueva) o usa "
    "ficheros .wav, que no lo necesitan."
)


def ffmpeg_available() -> bool:
    """``True`` si pydub encuentra ffmpeg (en el PATH o en ``AudioSegment.converter``)."""
    try:
        from pydub import AudioSegment

        converter = str(getattr(AudioSegment, "converter", "") or "ffmpeg")
    except ImportError:  # pragma: no cover - pydub es dependencia obligatoria
        converter = "ffmpeg"
    return bool(shutil.which(converter) or shutil.which("ffmpeg"))


def _require_ffmpeg(what: str) -> None:
    if not ffmpeg_available():
        raise AssembleError(f"no se encuentra ffmpeg, necesario para {what}. {FFMPEG_HINT}")


def _load_audio_file(path: Path, sr: int) -> np.ndarray:
    from pydub import AudioSegment

    if path.suffix.lower() != ".wav":
        _require_ffmpeg(f"leer '{path.name}' (formato {path.suffix or 'desconocido'})")
    try:
        return _segment_to_array(AudioSegment.from_file(str(path)), sr)
    except Exception as exc:
        raise AssembleError(f"no se pudo leer el audio {path}: {exc}") from exc


def _fade(x: np.ndarray, fade_in: int, fade_out: int) -> np.ndarray:
    x = x.copy()
    n = x.size
    fi = min(fade_in, n)
    fo = min(fade_out, n)
    if fi > 0:
        x[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)
    if fo > 0:
        x[n - fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)
    return x


def _frame_rms_db(x: np.ndarray, sr: int) -> np.ndarray:
    frame = max(1, int(0.05 * sr))
    n = x.size // frame
    if n == 0:
        return np.array([20 * np.log10(max(float(np.sqrt(np.mean(x**2))) if x.size else 0, 1e-10))])
    frames = x[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-10))


def normalize_loudness(x: np.ndarray, sr: int, target_lufs: float = -16.0,
                       peak_dbfs: float = -1.0) -> np.ndarray:
    """Normaliza a ``target_lufs`` (pyloudnorm si está instalado; si no, RMS con puerta).

    Después limita el pico a ``peak_dbfs`` con una ganancia global (sin compresión).
    """
    if x.size == 0 or not np.any(x):
        return x
    gain_db: float | None = None
    try:
        import pyloudnorm  # type: ignore[import-untyped]

        if x.size >= int(0.5 * sr):
            loudness = pyloudnorm.Meter(sr).integrated_loudness(x.astype(np.float64))
            if math.isfinite(loudness):
                gain_db = target_lufs - loudness
    except ImportError:
        pass
    if gain_db is None:
        # Aproximación: RMS de las partes activas (>-50 dBFS); voz ≈ LUFS + ~2 dB.
        db = _frame_rms_db(x, sr)
        active = db[db > -50.0]
        if active.size == 0:
            return x
        rms_db = 10 * np.log10(np.mean(10 ** (active / 10)))
        gain_db = (target_lufs - 2.0) - rms_db
    y = x * np.float32(10 ** (gain_db / 20))
    peak = float(np.max(np.abs(y)))
    limit = 10 ** (peak_dbfs / 20)
    if peak > limit:
        y *= np.float32(limit / peak)
    return y.astype(np.float32, copy=False)


# --------------------------------------------------------------------------- #
# Caché de síntesis
# --------------------------------------------------------------------------- #


class SynthesisCache:
    """Caché en disco de frases sintetizadas (``<dir>/<sha256>.npz``)."""

    def __init__(self, directory: Path | None) -> None:
        self.directory = Path(directory) if directory else None
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(text: str, voice: Voice, lang: str, speed: float, engine: str,
            engine_tag: str = "") -> str:
        """Clave de caché. ``engine_tag`` es el ``cache_tag`` del motor (modelo,
        versión y parámetros): si cambia, la frase se vuelve a sintetizar."""
        payload = json.dumps(
            [text, voice.fingerprint(), lang, round(float(speed), 4), engine, engine_tag],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> tuple[np.ndarray, int] | None:
        if not self.directory:
            return None
        path = self.directory / f"{key}.npz"
        if not path.is_file():
            self.misses += 1
            return None
        try:
            with np.load(path) as data:
                self.hits += 1
                return data["audio"].astype(np.float32), int(data["sr"])
        except Exception:  # fichero corrupto: se regenera
            self.misses += 1
            return None

    def put(self, key: str, audio: np.ndarray, sr: int) -> None:
        if not self.directory:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.directory / f"{key}.tmp.npz"
        np.savez(tmp, audio=audio.astype(np.float32), sr=np.int64(sr))
        tmp.replace(self.directory / f"{key}.npz")


# --------------------------------------------------------------------------- #
# Síntesis
# --------------------------------------------------------------------------- #


def resolve_speech(seg: Speech, script: ParsedScript | None, voices_dir: Path | None,
                   options: AssembleOptions) -> ResolvedSpeech:
    """Calcula voz, motor, idioma y velocidad efectivos de una frase."""
    meta = script.meta if script else None
    root = Path(voices_dir) if voices_dir else default_voices_dir()
    voice: Voice | None
    try:
        voice = get_voice(seg.voice, root)
    except VoiceNotFoundError:
        voice = None
    engine = (
        options.engine_override
        or seg.engine
        or (meta.default_engine if meta else None)
        or (voice.engine if voice else None)
        or options.default_engine
    ).lower()
    if voice is None:
        if engine != "dummy":
            where = f"línea {seg.line}: " if seg.line else ""
            raise AssembleError(f"{where}la voz '{seg.voice}' no existe en {root}")
        voice = Voice(name=seg.voice, path=root / seg.voice)  # voz efímera para el dummy
    lang = seg.lang or (meta.lang if meta else None) or voice.lang or options.default_lang
    speed = seg.speed or voice.speed or 1.0
    return ResolvedSpeech(voice=voice, engine=engine, lang=lang, speed=float(speed))


def synthesize_speech(
    seg: Speech,
    *,
    script: ParsedScript | None = None,
    voices_dir: str | Path | None = None,
    engine_resolver: EngineResolver | None = None,
    options: AssembleOptions | None = None,
    cache: SynthesisCache | None = None,
) -> tuple[np.ndarray, int]:
    """Sintetiza una frase (usando la caché). Devuelve ``(audio float32, sample_rate)``."""
    options = options or AssembleOptions()
    resolver = engine_resolver or get_engine
    if cache is None:
        cache = SynthesisCache(options.cache_dir)
    r = resolve_speech(seg, script, Path(voices_dir) if voices_dir else None, options)
    engine = resolver(r.engine)  # crear la instancia es barato: los modelos se cargan al sintetizar
    key = cache.key(seg.text, r.voice, r.lang, r.speed, r.engine, engine_cache_tag(engine))
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        audio = engine.synthesize(seg.text, r.voice, r.lang, r.speed)
    except NotImplementedError:
        raise
    except Exception as exc:
        where = f"línea {seg.line}: " if seg.line else ""
        raise AssembleError(f"{where}fallo al sintetizar con '{r.engine}': {exc}") from exc
    audio = _to_mono_float(audio)
    sr = int(engine.sample_rate)
    cache.put(key, audio, sr)
    return audio, sr


# --------------------------------------------------------------------------- #
# Montaje
# --------------------------------------------------------------------------- #


@dataclass
class _BgTrack:
    path: Path
    volume: float
    fade_in: float
    start: int
    end: int | None = None
    fade_out: float = 0.0


def _resolve_path(raw: str, options: AssembleOptions, line: int | None) -> Path:
    where = f"línea {line}: " if line else ""
    path = Path(raw)
    if not options.allow_external_paths:
        if path.is_absolute() or path.drive or path.root or ".." in path.parts:
            raise AssembleError(
                f"{where}ruta de audio no permitida '{raw}': en modo remoto solo se admiten "
                "rutas relativas a la carpeta del guion o del proyecto, sin '..'"
            )
        roots = [r.resolve() for r in (options.base_dir, PROJECT_ROOT) if r is not None]
        for root in roots:
            cand = (root / path).resolve()
            if cand.is_relative_to(root) and cand.is_file():
                return cand
        raise AssembleError(f"{where}no existe el fichero de audio '{raw}'")
    if not path.is_absolute():
        candidates = [options.base_dir / path] if options.base_dir else []
        candidates += [Path.cwd() / path, PROJECT_ROOT / path]
        path = next((c for c in candidates if c.is_file()), candidates[0])
    if not path.is_file():
        raise AssembleError(f"{where}no existe el fichero de audio '{raw}' (buscado en {path})")
    return path


def _speech_mask(intervals: list[tuple[int, int]], total: int, hop: int, ramp_frames: int,
                 min_gap_frames: int) -> np.ndarray:
    """Máscara por tramas (hop muestras) de "hay voz", con huecos cortos rellenados."""
    n = total // hop + 1
    mask = np.zeros(n, dtype=bool)
    for a, b in intervals:
        mask[a // hop: b // hop + 1] = True
    if mask.any() and min_gap_frames > 0:
        idx = np.flatnonzero(mask)
        gaps = np.diff(idx)
        for i in np.flatnonzero((gaps > 1) & (gaps <= min_gap_frames)):
            mask[idx[i]: idx[i + 1]] = True
    if ramp_frames > 0 and mask.any():
        # Ensancha la máscara para que la música baje antes de que empiece la voz.
        kernel = np.ones(2 * ramp_frames + 1)
        mask = np.convolve(mask.astype(float), kernel, mode="same") > 0
    return mask


def _mix_background(out: np.ndarray, track: _BgTrack, music: np.ndarray, sr: int,
                    mask: np.ndarray, hop: int, options: AssembleOptions) -> None:
    start = track.start
    end = min(track.end if track.end is not None else out.size, out.size)
    length = end - start
    if length <= 0 or music.size == 0:
        return
    reps = int(math.ceil(length / music.size))
    clip = np.tile(music, reps)[:length] if reps > 1 else music[:length].copy()
    # Envolvente de ducking a resolución de trama, suavizada y luego interpolada.
    full = min(1.0, track.volume * options.bg_full_ratio)
    f0, f1 = start // hop, end // hop + 1
    gains = np.where(mask[f0:f1], track.volume, full).astype(np.float64)
    ramp = max(1, int(options.duck_ramp * sr / hop))
    if gains.size > 1 and ramp > 1:
        padded = np.pad(gains, (ramp // 2, ramp - ramp // 2 - 1), mode="edge")
        gains = np.convolve(padded, np.ones(ramp) / ramp, mode="valid")
    frame_pos = (np.arange(f0, f0 + gains.size) * hop) - start
    env = np.interp(np.arange(length), frame_pos, gains).astype(np.float32)
    clip = _fade(clip * env, int(track.fade_in * sr), int(track.fade_out * sr))
    out[start:end] += clip


def render(
    script: ParsedScript | Sequence[Segment],
    *,
    voices_dir: str | Path | None = None,
    engine_resolver: EngineResolver | None = None,
    options: AssembleOptions | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[np.ndarray, int]:
    """Monta el episodio y devuelve ``(audio float32 mono, sample_rate)`` sin exportar."""
    try:
        return _render(script, voices_dir=voices_dir, engine_resolver=engine_resolver,
                       options=options, progress=progress)
    except (OverflowError, MemoryError) as exc:
        raise AssembleError(
            "el episodio es demasiado largo para montarlo en memoria (revisa las pausas, "
            f"fundidos y la música del guion): {type(exc).__name__}: {exc}"
        ) from exc


def _render(
    script: ParsedScript | Sequence[Segment],
    *,
    voices_dir: str | Path | None,
    engine_resolver: EngineResolver | None,
    options: AssembleOptions | None,
    progress: ProgressCallback | None,
) -> tuple[np.ndarray, int]:
    options = options or AssembleOptions()
    if not isinstance(script, ParsedScript):
        script = ParsedScript(segments=list(script))
    sr = options.sample_rate
    cache = SynthesisCache(options.cache_dir)
    vdir = Path(voices_dir) if voices_dir else None

    placed: list[tuple[int, np.ndarray]] = []
    speech_intervals: list[tuple[int, int]] = []
    bg_tracks: list[_BgTrack] = []
    active_bg: _BgTrack | None = None
    music_cache: dict[Path, np.ndarray] = {}
    cursor = 0
    prev: Segment | None = None
    total = len(script.segments)

    def load(path: Path) -> np.ndarray:
        if path not in music_cache:
            music_cache[path] = _load_audio_file(path, sr)
        return music_cache[path]

    for i, seg in enumerate(script.segments, start=1):
        if isinstance(seg, Speech):
            if progress:
                preview = seg.text if len(seg.text) <= 60 else seg.text[:57] + "..."
                progress(i, total, f"Sintetizando [{seg.voice}] {preview}")
            if isinstance(prev, Speech):
                cursor += int(options.chunk_gap * sr)
            audio, engine_sr = synthesize_speech(
                seg, script=script, voices_dir=vdir, engine_resolver=engine_resolver,
                options=options, cache=cache,
            )
            audio = _resample(audio, engine_sr, sr)
            placed.append((cursor, audio))
            speech_intervals.append((cursor, cursor + audio.size))
            cursor += audio.size
        elif isinstance(seg, Pause):
            if progress:
                progress(i, total, f"Pausa de {seg.seconds:g} s")
            cursor += int(round(seg.seconds * sr))
        elif isinstance(seg, Music):
            if seg.stop:
                if progress:
                    progress(i, total, "Fin de la música de fondo")
                if active_bg is not None:
                    active_bg.fade_out = seg.fade
                    active_bg.end = cursor + int(seg.fade * sr)
                    active_bg = None
            elif seg.background:
                if progress:
                    progress(i, total, f"Música de fondo: {seg.path}")
                path = _resolve_path(seg.path, options, seg.line)
                load(path)
                if active_bg is not None:  # una nueva música de fondo sustituye a la anterior
                    active_bg.fade_out = seg.fade
                    active_bg.end = cursor + int(seg.fade * sr)
                active_bg = _BgTrack(path=path, volume=seg.volume, fade_in=seg.fade,
                                     start=cursor, fade_out=seg.fade)
                bg_tracks.append(active_bg)
            else:
                if progress:
                    progress(i, total, f"Música: {seg.path}")
                path = _resolve_path(seg.path, options, seg.line)
                clip = _fade(load(path) * np.float32(seg.volume),
                             int(seg.fade * sr), int(seg.fade * sr))
                placed.append((cursor, clip))
                cursor += clip.size
        elif isinstance(seg, Sfx):
            if progress:
                progress(i, total, f"Efecto: {seg.path}")
            path = _resolve_path(seg.path, options, seg.line)
            placed.append((cursor, load(path) * np.float32(seg.volume)))
        prev = seg

    length = max([cursor] + [s + a.size for s, a in placed]
                 + [t.end for t in bg_tracks if t.end is not None])
    if length > MAX_EPISODE_SECONDS * sr:
        raise OverflowError(f"{length / sr:.0f} s > {MAX_EPISODE_SECONDS} s")
    out = np.zeros(length, dtype=np.float32)
    for start, audio in placed:
        out[start:start + audio.size] += audio

    if bg_tracks:
        hop = max(1, sr // 100)  # tramas de 10 ms
        mask = _speech_mask(speech_intervals, length, hop,
                            ramp_frames=int(options.duck_ramp * 100),
                            min_gap_frames=int(options.duck_min_gap * 100))
        for track in bg_tracks:
            _mix_background(out, track, music_cache[track.path], sr, mask, hop, options)

    if progress:
        progress(total, total, "Mezclando y normalizando")
    if options.target_lufs is not None:
        out = normalize_loudness(out, sr, options.target_lufs, options.peak_dbfs)
    else:
        peak = float(np.max(np.abs(out))) if out.size else 0.0
        if peak > 1.0:
            out /= peak
    return out, sr


def assemble(
    script: ParsedScript | Sequence[Segment],
    *,
    voices_dir: str | Path | None = None,
    engine_resolver: EngineResolver | None = None,
    options: AssembleOptions | None = None,
    progress: ProgressCallback | None = None,
) -> "AudioSegment":  # noqa: F821
    """Monta el episodio y devuelve un ``pydub.AudioSegment`` (mono, 16 bit)."""
    audio, sr = render(script, voices_dir=voices_dir, engine_resolver=engine_resolver,
                       options=options, progress=progress)
    return _array_to_segment(audio, sr)


def export_audio(audio: "AudioSegment", path: str | Path, *,  # noqa: F821
                 bitrate: str = "192k", tags: dict[str, str] | None = None) -> Path:
    """Exporta a MP3 (``bitrate``) o WAV/FLAC/OGG según la extensión (vía ffmpeg)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = path.suffix.lower().lstrip(".") or "mp3"
    if fmt not in ("mp3", "wav", "flac", "ogg", "m4a"):
        raise AssembleError(f"formato de salida no soportado: .{fmt} (usa .mp3 o .wav)")
    if fmt != "wav":
        _require_ffmpeg(f"exportar a .{fmt}")
    kwargs: dict[str, object] = {"format": "ipod" if fmt == "m4a" else fmt}
    if fmt in ("mp3", "ogg", "m4a"):
        kwargs["bitrate"] = bitrate
    if tags and fmt == "mp3":
        kwargs["tags"] = tags
    try:
        audio.export(str(path), **kwargs).close()  # pydub devuelve el fichero abierto
    except FileNotFoundError as exc:  # ffmpeg desapareció o AudioSegment.converter inválido
        if fmt == "wav":
            raise
        raise AssembleError(f"no se pudo ejecutar ffmpeg para exportar a .{fmt}: {exc}. "
                            f"{FFMPEG_HINT}") from exc
    return path


def generate(
    script_path: str | Path,
    output_path: str | Path,
    *,
    voices_dir: str | Path | None = None,
    engine_resolver: EngineResolver | None = None,
    options: AssembleOptions | None = None,
    progress: ProgressCallback | None = None,
    max_chars: int = 250,
    bitrate: str = "192k",
) -> Path:
    """Atajo: parsea ``script_path``, monta y exporta a ``output_path``."""
    script_path = Path(script_path)
    script = parse_file(script_path, max_chars=max_chars)
    options = options or AssembleOptions()
    if options.base_dir is None:
        options.base_dir = script_path.resolve().parent
    audio = assemble(script, voices_dir=voices_dir, engine_resolver=engine_resolver,
                     options=options, progress=progress)
    tags = {"title": script.meta.title} if script.meta.title else None
    return export_audio(audio, output_path, bitrate=bitrate, tags=tags)
