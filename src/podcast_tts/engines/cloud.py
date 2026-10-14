"""Utilidades comunes de los motores en la nube (solo stdlib: ``urllib.request`` + ``json``).

- :class:`CloudEngine`: base con lectura perezosa de claves (``podcast_tts.config``),
  peticiones HTTP con *timeout* y reintentos ante 429/5xx, y mensajes de error en castellano.
- :func:`pcm16_to_float32`: convierte PCM 16 bit little-endian mono a float32 en [-1, 1].

Las claves de API nunca se incluyen en mensajes de error ni en el log.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import COMMERCIAL_DEPENDS, EngineError, LicenseInfo

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = ["CloudEngine", "pcm16_to_float32", "COMMERCIAL_DEPENDS"]

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
USER_AGENT = "podcast-tts (python-urllib)"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def pcm16_to_float32(data: bytes) -> np.ndarray:
    """PCM 16 bit con signo, little-endian, mono -> ``np.ndarray`` float32 en [-1, 1]."""
    if len(data) % 2:
        data = data[:-1]  # byte suelto al final: se descarta
    pcm = np.frombuffer(data, dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


class CloudEngine:
    """Base de los motores en la nube.

    Las subclases definen ``name``, ``provider`` (nombre legible), ``license_info``,
    ``required_config`` y ``key_env`` (variable con la clave de API), e implementan
    :meth:`synthesize` usando :meth:`_request`.

    Parámetros comunes:
        api_key: clave explícita (si no, se lee en cada síntesis de entorno/``.env``).
        timeout: segundos de espera por petición.
        max_retries: reintentos ante 429/5xx o errores de red.
        retry_backoff: espera base entre reintentos (se dobla en cada uno).
    """

    name = "cloud"
    provider = "proveedor"
    kind = "cloud"
    key_env = ""
    required_config: tuple[str, ...] = ()
    license_info = LicenseInfo(name="términos del proveedor", commercial_use=COMMERCIAL_DEPENDS)

    def __init__(self, api_key: str | None = None, *, timeout: float = 60.0, max_retries: int = 2,
                 retry_backoff: float = 1.0) -> None:
        self._api_key = api_key
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = max(0.0, float(retry_backoff))

    def __repr__(self) -> str:  # nunca mostrar la clave
        return f"{type(self).__name__}(timeout={self.timeout}, max_retries={self.max_retries})"

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    # ------------------------------------------------------------------ claves
    def _config_value(self, name: str) -> str | None:
        from ..config import get_key

        return get_key(name)

    def _require(self, name: str, what: str) -> str:
        value = self._config_value(name)
        if not value:
            raise EngineError(
                f"falta {what} de {self.provider} ({name}). Configúrala con "
                f"`python -m podcast_tts config set {name}` o en la pestaña Ajustes de la UI."
            )
        return value

    def _key(self) -> str:
        if self._api_key:
            return self._api_key
        return self._require(self.key_env, "la clave de API")

    # ------------------------------------------------------------------ voces
    def _voice_id(self, voice: "Voice") -> str:
        vid = (getattr(voice, "provider_voice_id", None) or "").strip()
        if not vid:
            raise EngineError(
                f"la voz '{voice.name}' no tiene 'provider_voice_id' para {self.provider}. "
                f"Créala con: python -m podcast_tts voices add {voice.name} --engine {self.name} "
                "--provider-voice-id <ID>"
            )
        return vid

    @staticmethod
    def _options(voice: "Voice") -> dict[str, Any]:
        opts = getattr(voice, "provider_options", None)
        return dict(opts) if isinstance(opts, dict) else {}

    # ------------------------------------------------------------------ HTTP
    def _sanitize(self, text: str, secrets: tuple[str, ...]) -> str:
        for s in secrets:
            if s:
                text = text.replace(s, "****")
        return text

    def _error_detail(self, body: bytes) -> str:
        """Extrae el mensaje de error de la respuesta (JSON de OpenAI/ElevenLabs o texto)."""
        text = body[:2000].decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(text)
        except ValueError:
            return " ".join(text.split())[:300]
        msg: Any = data
        if isinstance(data, dict):
            msg = data.get("error") or data.get("detail") or data.get("message") or data
            if isinstance(msg, dict):
                msg = msg.get("message") or msg.get("status") or msg
        return " ".join(str(msg).split())[:300]

    def _http_error(self, status: int, detail: str) -> EngineError:
        p = self.provider
        base = {
            400: f"{p} rechazó la petición (400, parámetros inválidos)",
            401: f"clave de API de {p} inválida, caducada o ausente (401)",
            402: f"{p}: hace falta un plan de pago o saldo (402)",
            403: f"{p} denegó el acceso (403): la clave no tiene permiso para esta voz/modelo "
                 "o tu plan no lo incluye",
            404: f"{p}: recurso no encontrado (404); revisa el ID de voz, el modelo o la región",
            408: f"{p}: tiempo de espera agotado en el servidor (408)",
            413: f"{p}: el texto es demasiado largo (413)",
            422: f"{p} no pudo procesar la petición (422, parámetros inválidos)",
            429: f"{p}: límite de peticiones o cuota agotada (429); espera o revisa tu plan",
        }.get(status)
        if base is None:
            base = (f"{p}: error del servidor ({status}); inténtalo más tarde" if status >= 500
                    else f"{p} devolvió el error HTTP {status}")
        return EngineError(f"{base}. Detalle: {detail}" if detail else base)

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        delay = self.retry_backoff * (2 ** attempt)
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 30.0))
            except ValueError:
                pass
        if delay > 0:
            time.sleep(delay)

    def _request(self, url: str, *, data: bytes, headers: dict[str, str],
                 secrets: tuple[str, ...] = ()) -> bytes:
        """POST con reintentos. Devuelve el cuerpo de la respuesta o lanza :class:`EngineError`."""
        headers = {"User-Agent": USER_AGENT, **headers}
        last: EngineError | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read() or b""
                except Exception:  # noqa: BLE001
                    body = b""
                detail = self._sanitize(self._error_detail(body), secrets)
                last = self._http_error(exc.code, detail)
                if exc.code not in _RETRY_STATUS or attempt >= self.max_retries:
                    raise last from None
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                log.warning("%s: HTTP %s, reintento %d/%d", self.provider, exc.code, attempt + 1,
                            self.max_retries)
                self._sleep(attempt, retry_after)
            except (TimeoutError, socket.timeout):
                last = EngineError(f"{self.provider}: tiempo de espera agotado ({self.timeout:g} s)")
                if attempt >= self.max_retries:
                    raise last from None
                self._sleep(attempt, None)
            except urllib.error.URLError as exc:
                reason = self._sanitize(str(exc.reason), secrets)
                last = EngineError(f"no se pudo conectar con {self.provider}: {reason}")
                if attempt >= self.max_retries:
                    raise last from None
                self._sleep(attempt, None)
        raise last or EngineError(f"{self.provider}: la petición falló")  # pragma: no cover

    def _to_audio(self, data: bytes, text: str) -> np.ndarray:
        audio = pcm16_to_float32(data)
        if audio.size == 0:
            raise EngineError(f"{self.provider} devolvió audio vacío para: {text[:60]!r}")
        return audio

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        raise NotImplementedError
