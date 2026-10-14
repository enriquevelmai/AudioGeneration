"""Cloud engines with a mocked ``urllib.request.urlopen`` (no network, no real keys)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import xml.dom.minidom
from email.message import Message
from pathlib import Path

import numpy as np
import pytest

from podcast_tts.engines import EngineError, engine_info, get_engine
from podcast_tts.engines.azure import AzureEngine, build_ssml
from podcast_tts.engines.cloud import pcm16_to_float32
from podcast_tts.engines.elevenlabs import ElevenLabsEngine
from podcast_tts.engines.openai import OpenAIEngine
from podcast_tts.voices import Voice

FAKE_KEY = "sk-test-0123456789abcdef"
PCM = np.array([0, 16384, -16384, 32767, -32768], dtype="<i2").tobytes()
EXPECTED = np.array([0.0, 0.5, -0.5, 32767 / 32768, -1.0], dtype=np.float32)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """No keys from the real environment and an empty .env in tmp_path."""
    for k in ("ELEVENLABS_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PODCAST_TTS_ENV_FILE", str(tmp_path / ".env"))


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class FakeUrlopen:
    """Replaces ``urllib.request.urlopen``: records the requests and returns responses."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses) or [PCM]
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        self.timeouts.append(timeout)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, BaseException):
            raise item
        return FakeResponse(item)

    @property
    def last(self) -> urllib.request.Request:
        return self.requests[-1]

    def header(self, name: str) -> str | None:
        return dict(self.last.header_items()).get(name.capitalize())


def http_error(code: int, body: dict | str = "", retry_after: str | None = None):
    hdrs = Message()
    if retry_after:
        hdrs["Retry-After"] = retry_after
    raw = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
    return urllib.error.HTTPError("https://x", code, "err", hdrs, io.BytesIO(raw))


@pytest.fixture
def fake(monkeypatch):
    f = FakeUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", f)
    return f


def cloud_voice(tmp_path: Path, vid: str, engine: str, **options) -> Voice:
    return Voice(name="v", path=tmp_path / "v", engine=engine, provider_voice_id=vid,
                 provider_options=options)


def test_pcm16_to_float32() -> None:
    out = pcm16_to_float32(PCM)
    assert out.dtype == np.float32
    np.testing.assert_allclose(out, EXPECTED)
    assert pcm16_to_float32(PCM + b"\x01").size == 5  # stray byte dropped
    assert pcm16_to_float32(b"").size == 0


# --------------------------------------------------------------------------- ElevenLabs


def test_elevenlabs_request(fake, tmp_path) -> None:
    eng = ElevenLabsEngine(api_key=FAKE_KEY)
    voice = cloud_voice(tmp_path, "abc123", "elevenlabs", voice_settings={"stability": 0.4})
    audio = eng.synthesize("Hola, ¿qué tal?", voice, "es", speed=1.1)
    np.testing.assert_allclose(audio, EXPECTED)
    assert eng.sample_rate == 24000
    req = fake.last
    assert req.full_url == "https://api.elevenlabs.io/v1/text-to-speech/abc123?output_format=pcm_24000"
    assert req.get_method() == "POST"
    assert fake.header("xi-api-key") == FAKE_KEY
    assert fake.header("Content-Type") == "application/json"
    body = json.loads(req.data.decode("utf-8"))
    assert body["text"] == "Hola, ¿qué tal?"
    assert body["model_id"] == "eleven_multilingual_v2"
    assert body["voice_settings"] == {"stability": 0.4, "speed": 1.1}
    assert "language_code" not in body  # multilingual_v2 does not support it
    assert fake.timeouts[-1] == 60.0


def test_elevenlabs_language_code_and_speed_clamp(fake, tmp_path) -> None:
    eng = ElevenLabsEngine(api_key=FAKE_KEY, model_id="eleven_flash_v2_5")
    eng.synthesize("Hello", cloud_voice(tmp_path, "id/x", "elevenlabs"), "en-US", speed=2.0)
    body = json.loads(fake.last.data)
    assert body["language_code"] == "en"
    assert body["voice_settings"]["speed"] == 1.2
    assert "/text-to-speech/id%2Fx?" in fake.last.full_url
    # speed 1.0 -> no voice_settings
    eng.synthesize("Hello", cloud_voice(tmp_path, "id", "elevenlabs"), "en", speed=1.0)
    assert "voice_settings" not in json.loads(fake.last.data)


def test_elevenlabs_key_from_env_file(fake, tmp_path) -> None:
    from podcast_tts import config

    eng = ElevenLabsEngine()
    voice = cloud_voice(tmp_path, "abc", "elevenlabs")
    with pytest.raises(EngineError, match="ELEVENLABS_API_KEY"):
        eng.synthesize("Hola", voice, "es")
    assert fake.requests == []
    config.set_key("ELEVENLABS_API_KEY", FAKE_KEY)
    eng.synthesize("Hola", voice, "es")
    assert fake.header("xi-api-key") == FAKE_KEY


# --------------------------------------------------------------------------- Azure


def test_azure_request(fake, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AZURE_SPEECH_KEY", FAKE_KEY)
    monkeypatch.setenv("AZURE_SPEECH_REGION", "westeurope")
    eng = AzureEngine()
    voice = cloud_voice(tmp_path, "es-ES-AlvaroNeural", "azure")
    audio = eng.synthesize("Tom & Jerry <3", voice, "es", speed=1.25)
    np.testing.assert_allclose(audio, EXPECTED)
    req = fake.last
    assert req.full_url == "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1"
    assert fake.header("Ocp-Apim-Subscription-Key") == FAKE_KEY
    assert fake.header("Content-Type") == "application/ssml+xml"
    assert fake.header("X-Microsoft-OutputFormat") == "raw-24khz-16bit-mono-pcm"
    ssml = req.data.decode("utf-8")
    doc = xml.dom.minidom.parseString(ssml)  # well-formed XML (escaped text)
    speak = doc.documentElement
    assert speak.getAttribute("xml:lang") == "es-ES"
    assert speak.getElementsByTagName("voice")[0].getAttribute("name") == "es-ES-AlvaroNeural"
    prosody = speak.getElementsByTagName("prosody")[0]
    assert prosody.getAttribute("rate") == "+25%"
    assert prosody.firstChild.data == "Tom & Jerry <3"


def test_azure_ssml_variants() -> None:
    plain = build_ssml("Hi", "en-US-JennyNeural", "en")
    assert "<prosody" not in plain and 'xml:lang="en-US"' in plain
    multi = build_ssml("Hello", "es-ES-ArabellaMultilingualNeural", "en", 0.9,
                       {"style": "cheerful"})
    assert '<lang xml:lang="en-US">' in multi and 'rate="-10%"' in multi
    assert '<mstts:express-as style="cheerful">' in multi
    xml.dom.minidom.parseString(multi)


def test_azure_missing_region(fake, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AZURE_SPEECH_KEY", FAKE_KEY)
    with pytest.raises(EngineError, match="AZURE_SPEECH_REGION"):
        AzureEngine().synthesize("Hola", cloud_voice(tmp_path, "es-ES-AlvaroNeural", "azure"), "es")
    with pytest.raises(EngineError, match="region"):
        AzureEngine(region="west europe/../x").synthesize(
            "Hola", cloud_voice(tmp_path, "es-ES-AlvaroNeural", "azure"), "es")
    assert fake.requests == []


# --------------------------------------------------------------------------- OpenAI


def test_openai_request(fake, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    eng = OpenAIEngine()
    voice = cloud_voice(tmp_path, "nova", "openai", instructions="Warm tone")
    audio = eng.synthesize("Hola", voice, "es", speed=1.5)
    np.testing.assert_allclose(audio, EXPECTED)
    req = fake.last
    assert req.full_url == "https://api.openai.com/v1/audio/speech"
    assert fake.header("Authorization") == f"Bearer {FAKE_KEY}"
    body = json.loads(req.data)
    assert body == {"model": "gpt-4o-mini-tts", "input": "Hola", "voice": "nova",
                    "response_format": "pcm", "speed": 1.5, "instructions": "Warm tone"}
    eng2 = OpenAIEngine(model="tts-1-hd")
    eng2.synthesize("Hola", cloud_voice(tmp_path, "alloy", "openai"), "es", speed=1.0)
    body = json.loads(fake.last.data)
    assert body["model"] == "tts-1-hd" and "speed" not in body


# --------------------------------------------------------------------------- Errors


@pytest.mark.parametrize("code, pattern", [
    (401, "OpenAI API key is invalid"),
    (403, "denied access"),
    (404, "not found"),
    (400, "rejected the request"),
])
def test_http_errors_are_clear_and_hide_key(fake, tmp_path, code, pattern) -> None:
    fake.responses = [http_error(code, {"error": {"message": f"bad key {FAKE_KEY}"}})]
    eng = OpenAIEngine(api_key=FAKE_KEY, retry_backoff=0)
    with pytest.raises(EngineError, match=pattern) as exc_info:
        eng.synthesize("Hola", cloud_voice(tmp_path, "nova", "openai"), "es")
    assert FAKE_KEY not in str(exc_info.value)
    assert "bad key ****" in str(exc_info.value)
    assert len(fake.requests) == 1  # 4xx (except 429) is not retried
    assert FAKE_KEY not in repr(eng)


def test_retries_on_429_and_5xx(fake, tmp_path, monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    fake.responses = [http_error(429, retry_after="2"), http_error(503), PCM]
    eng = ElevenLabsEngine(api_key=FAKE_KEY, max_retries=2, retry_backoff=0.5)
    audio = eng.synthesize("Hola", cloud_voice(tmp_path, "abc", "elevenlabs"), "es")
    assert audio.size == 5 and len(fake.requests) == 3
    assert sleeps == [2.0, 1.0]


def test_quota_error_after_retries(fake, tmp_path) -> None:
    body = {"detail": {"status": "quota_exceeded", "message": "Quota exceeded"}}
    fake.responses = [http_error(429, body), http_error(429, body)]
    eng = ElevenLabsEngine(api_key=FAKE_KEY, max_retries=1, retry_backoff=0)
    with pytest.raises(EngineError, match="quota exceeded.*Quota exceeded"):
        eng.synthesize("Hola", cloud_voice(tmp_path, "abc", "elevenlabs"), "es")
    assert len(fake.requests) == 2


def test_network_errors(fake, tmp_path) -> None:
    fake.responses = [urllib.error.URLError("no network")]
    eng = OpenAIEngine(api_key=FAKE_KEY, max_retries=0)
    with pytest.raises(EngineError, match="could not connect to OpenAI"):
        eng.synthesize("Hola", cloud_voice(tmp_path, "nova", "openai"), "es")
    fake.responses = [TimeoutError()]
    with pytest.raises(EngineError, match="timed out"):
        eng.synthesize("Hola", cloud_voice(tmp_path, "nova", "openai"), "es")


def test_missing_provider_voice_id_and_empty(fake, tmp_path) -> None:
    eng = OpenAIEngine(api_key=FAKE_KEY)
    with pytest.raises(EngineError, match="provider_voice_id"):
        eng.synthesize("Hola", Voice("ana", tmp_path), "es")
    assert eng.synthesize("   ", Voice("ana", tmp_path), "es").size == 0
    fake.responses = [b""]
    with pytest.raises(EngineError, match="empty audio"):
        eng.synthesize("Hola", cloud_voice(tmp_path, "nova", "openai"), "es")


def test_registry_cloud_metadata(monkeypatch) -> None:
    info = engine_info(check_cuda=False)
    for name in ("elevenlabs", "azure", "openai"):
        assert info[name]["kind"] == "cloud"
        assert info[name]["configured"] is False
        assert info[name]["commercial_use"] in (True, "depends on plan")
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    assert engine_info(check_cuda=False)["openai"]["configured"] is True
    assert get_engine("openai").sample_rate == 24000


def test_assembler_with_cloud_voice(fake, tmp_path, monkeypatch) -> None:
    """A sentence with a cloud voice goes through the assembler's cache and resampling."""
    from podcast_tts.assembler import AssembleOptions, synthesize_speech
    from podcast_tts.script_parser import Speech
    from podcast_tts.voices import add_voice

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    add_voice("nova", None, engine="openai", provider_voice_id="nova", voices_dir=tmp_path / "v")
    opts = AssembleOptions(cache_dir=tmp_path / "cache")
    audio, sr = synthesize_speech(Speech(voice="nova", text="Hola"), voices_dir=tmp_path / "v",
                                  options=opts)
    assert sr == 24000 and audio.size == 5
    synthesize_speech(Speech(voice="nova", text="Hola"), voices_dir=tmp_path / "v", options=opts)
    assert len(fake.requests) == 1  # the second time it comes from the cache
