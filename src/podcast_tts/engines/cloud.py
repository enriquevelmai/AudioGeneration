"""Shared utilities for the cloud engines (stdlib only: ``urllib.request`` + ``json``).

- :class:`CloudEngine`: base class with lazy key lookup (``podcast_tts.config``),
  HTTP requests with a *timeout* and retries on 429/5xx, and clear error messages.
- :func:`pcm16_to_float32`: converts 16-bit little-endian mono PCM to float32 in [-1, 1].

API keys are never included in error messages or in the log.
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
    """Signed 16-bit PCM, little-endian, mono -> float32 ``np.ndarray`` in [-1, 1]."""
    if len(data) % 2:
        data = data[:-1]  # stray trailing byte: drop it
    pcm = np.frombuffer(data, dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


class CloudEngine:
    """Base class of the cloud engines.

    Subclasses define ``name``, ``provider`` (readable name), ``license_info``,
    ``required_config`` and ``key_env`` (variable holding the API key), and implement
    :meth:`synthesize` using :meth:`_request`.

    Common parameters:
        api_key: explicit key (otherwise it is read from the environment/``.env`` on each synthesis).
        timeout: seconds to wait per request.
        max_retries: retries on 429/5xx or network errors.
        retry_backoff: base wait between retries (doubled on each one).
    """

    name = "cloud"
    provider = "provider"
    kind = "cloud"
    key_env = ""
    required_config: tuple[str, ...] = ()
    license_info = LicenseInfo(name="provider terms", commercial_use=COMMERCIAL_DEPENDS)

    def __init__(self, api_key: str | None = None, *, timeout: float = 60.0, max_retries: int = 2,
                 retry_backoff: float = 1.0) -> None:
        self._api_key = api_key
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = max(0.0, float(retry_backoff))

    def __repr__(self) -> str:  # never show the key
        return f"{type(self).__name__}(timeout={self.timeout}, max_retries={self.max_retries})"

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def cache_tag(self) -> str:
        """Engine and default model (subclasses add their ``model_id``)."""
        return self.name

    # ------------------------------------------------------------------ keys
    def _config_value(self, name: str) -> str | None:
        from ..config import get_key

        return get_key(name)

    def _require(self, name: str, what: str) -> str:
        value = self._config_value(name)
        if not value:
            raise EngineError(
                f"missing {what} for {self.provider} ({name}). Set it with "
                f"`python -m podcast_tts config set {name}` or in the Settings tab of the UI."
            )
        return value

    def _key(self) -> str:
        if self._api_key:
            return self._api_key
        return self._require(self.key_env, "the API key")

    # ------------------------------------------------------------------ voices
    def _voice_id(self, voice: "Voice") -> str:
        vid = (getattr(voice, "provider_voice_id", None) or "").strip()
        if not vid:
            raise EngineError(
                f"voice '{voice.name}' has no 'provider_voice_id' for {self.provider}. "
                f"Create it with: python -m podcast_tts voices add {voice.name} --engine {self.name} "
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
        """Extract the error message from the response (OpenAI/ElevenLabs JSON or plain text)."""
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
            400: f"{p} rejected the request (400, invalid parameters)",
            401: f"{p} API key is invalid, expired or missing (401)",
            402: f"{p}: a paid plan or credit is required (402)",
            403: f"{p} denied access (403): the key is not allowed to use this voice/model "
                 "or your plan does not include it",
            404: f"{p}: resource not found (404); check the voice ID, the model or the region",
            408: f"{p}: the server timed out (408)",
            413: f"{p}: the text is too long (413)",
            422: f"{p} could not process the request (422, invalid parameters)",
            429: f"{p}: rate limit or quota exceeded (429); wait or check your plan",
        }.get(status)
        if base is None:
            base = (f"{p}: server error ({status}); try again later" if status >= 500
                    else f"{p} returned HTTP error {status}")
        return EngineError(f"{base}. Details: {detail}" if detail else base)

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
        """POST with retries. Returns the response body or raises :class:`EngineError`."""
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
                log.warning("%s: HTTP %s, retry %d/%d", self.provider, exc.code, attempt + 1,
                            self.max_retries)
                self._sleep(attempt, retry_after)
            except (TimeoutError, socket.timeout):
                last = EngineError(f"{self.provider}: request timed out ({self.timeout:g} s)")
                if attempt >= self.max_retries:
                    raise last from None
                self._sleep(attempt, None)
            except urllib.error.URLError as exc:
                reason = self._sanitize(str(exc.reason), secrets)
                last = EngineError(f"could not connect to {self.provider}: {reason}")
                if attempt >= self.max_retries:
                    raise last from None
                self._sleep(attempt, None)
        raise last or EngineError(f"{self.provider}: the request failed")  # pragma: no cover

    def _to_audio(self, data: bytes, text: str) -> np.ndarray:
        audio = pcm16_to_float32(data)
        if audio.size == 0:
            raise EngineError(f"{self.provider} returned empty audio for: {text[:60]!r}")
        return audio

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray:
        raise NotImplementedError
