# Writing a third-party TTS engine (plugin)

`podcast_tts` discovers TTS engines through Python **entry points**, so anyone can publish a
package such as `podcast-tts-myengine` that adds a new engine **without touching this repository**.
Once installed in the same environment, the engine shows up everywhere:

- `python -m podcast_tts engines` (with its license and status),
- `generate --engine myengine`, `voices add --engine myengine`,
- script tags (`[voz:ana engine=myengine]`) and front matter (`engine: myengine`),
- the engine selectors and the "Ajustes" (settings) table of the Gradio UI.

## 1. The engine protocol

An engine is a class (or any callable that returns an object) implementing
`podcast_tts.engines.TTSEngine`:

| Member | Kind | Required | Meaning |
|---|---|---|---|
| `name` | class attribute (`str`) | yes | Short id, e.g. `"myengine"`. |
| `license_info` | class attribute (`LicenseInfo`) | strongly recommended | License of the model/service that produces the audio. Engines without it are treated as **non-commercial**. |
| `kind` | class attribute (`"local"` or `"cloud"`) | no (default `"local"`) | Shown in tables; cloud engines need no GPU. |
| `required_config` | class attribute (`tuple[str, ...]`) | no (default `()`) | Environment variables the engine needs (e.g. `("MYENGINE_API_KEY",)`). Used to report "configured / missing key" and accepted by `config set`. |
| `sample_rate` | property (`int`) | yes | Sample rate of the returned audio. Any rate works: the assembler resamples. |
| `synthesize(text, voice, lang, speed=1.0)` | method | yes | Returns a **mono `float32` `numpy` array in [-1, 1]**. |

Arguments of `synthesize`:

- `text`: one chunk of the script (by default at most 250 characters, split at sentence
  boundaries). Return an empty array for empty text.
- `voice`: a `podcast_tts.voices.Voice`. Useful fields: `name`, `lang`, `ref_wav` / `has_ref` /
  `ref_text` (voice cloning), `xtts_speaker`, `provider_voice_id` (the voice id in your service)
  and `provider_options` (a free-form `dict` from `voice.json`).
- `lang`: short ISO code (`"es"`, `"en"`, sometimes `"en-US"`).
- `speed`: factor, `1.0` = normal.

Raise `podcast_tts.engines.EngineError` with a clear message for expected failures (missing key,
unsupported language, HTTP errors). The CLI and UI show it to the user.

Constructor keyword arguments are optional: `get_engine("myengine")` calls the class with no
arguments and caches the instance (one per process); `get_engine("myengine", foo=1)` creates a
new, uncached instance.

### `LicenseInfo`

```python
from podcast_tts.engines import LicenseInfo, COMMERCIAL_DEPENDS

LicenseInfo(
    name="Apache-2.0",                      # short license name
    url="https://www.apache.org/licenses/LICENSE-2.0",
    commercial_use=True,                    # True, False or COMMERCIAL_DEPENDS ("depende del plan")
    notes="Weights released under Apache-2.0.",
)
```

Be accurate: the license that matters is the one of the **model weights or the service terms**,
not of your wrapper code. If commercial use is only allowed on paid plans, use
`COMMERCIAL_DEPENDS`. Engines with `commercial_use=False` trigger a license notice in the CLI
(`generate`, disable with `--no-license-notice`) and in the UI.

## 2. Declaring the entry point

In your package's `pyproject.toml`:

```toml
[project.entry-points."podcast_tts.engines"]
myengine = "podcast_tts_myengine:MyEngine"
```

- The entry point **name** is the engine name used in scripts and the CLI (lower case).
- The value is `module:attribute`; the attribute is the engine class (or a factory).
- Names of built-in engines (`f5`, `xtts`, `dummy`, `elevenlabs`, `azure`, `openai`) are
  reserved: a plugin using one of them is ignored with a warning.
- Plugins are only listed at startup; the module is imported **lazily**, the first time the
  engine is used or its metadata is requested. Keep heavy imports (torch, SDKs) inside
  methods so that `engines` and the UI stay fast.
- If the module fails to import, the engine is listed as "not available" with the error, and
  using it raises `EngineError`.

For quick experiments you can also register an engine at runtime:

```python
from podcast_tts.engines import register_engine
register_engine("myengine", "my_module:MyEngine")   # or the class itself
```

After installing a plugin in a running process, call `podcast_tts.engines.refresh_engines()`.

## 3. Minimal complete example

Layout:

```
podcast-tts-myengine/
├── pyproject.toml
└── src/podcast_tts_myengine/__init__.py
```

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "podcast-tts-myengine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["podcast-tts", "numpy"]

[project.entry-points."podcast_tts.engines"]
myengine = "podcast_tts_myengine:MyEngine"

[tool.hatch.build.targets.wheel]
packages = ["src/podcast_tts_myengine"]
```

`src/podcast_tts_myengine/__init__.py` (a cloud engine that calls a hypothetical REST API
returning 16-bit PCM at 22.05 kHz):

```python
"""MyEngine for podcast_tts."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import numpy as np

from podcast_tts.config import get_key
from podcast_tts.engines import EngineError, LicenseInfo


class MyEngine:
    name = "myengine"
    kind = "cloud"
    required_config = ("MYENGINE_API_KEY",)
    license_info = LicenseInfo(
        name="MyEngine Terms of Service",
        url="https://example.com/terms",
        commercial_use=True,
        notes="Commercial use allowed on paid plans.",
    )

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    @property
    def sample_rate(self) -> int:
        return 22050

    def synthesize(self, text, voice, lang, speed=1.0):
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        key = get_key("MYENGINE_API_KEY")          # environment variable or project .env
        if not key:
            raise EngineError("missing MYENGINE_API_KEY "
                              "(python -m podcast_tts config set MYENGINE_API_KEY)")
        if not voice.provider_voice_id:
            raise EngineError(f"voice '{voice.name}' has no provider_voice_id")
        body = {"text": text, "voice": voice.provider_voice_id, "lang": lang,
                "speed": speed, **voice.provider_options}
        req = urllib.request.Request(
            "https://api.example.com/v1/tts",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                pcm = resp.read()
        except urllib.error.HTTPError as exc:
            raise EngineError(f"MyEngine returned HTTP {exc.code}") from None  # never echo the key
        audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        return audio.clip(-1.0, 1.0)
```

Install it next to `podcast_tts` (in this project: add it to `pyproject.toml` and run
`uv lock --python 3.11` + `uv sync --extra dev`; for a quick local test,
`uv pip install -e path/to/podcast-tts-myengine`) and check:

```powershell
python -m podcast_tts engines
python -m podcast_tts config set MYENGINE_API_KEY
python -m podcast_tts voices add host --engine myengine --provider-voice-id voice-123 --lang en
python -m podcast_tts generate script.md --engine myengine
```

## 4. Checklist

- [ ] `synthesize` returns mono `float32` in [-1, 1] at `sample_rate`.
- [ ] `license_info` describes the model weights / service terms accurately.
- [ ] No heavy imports at module import time.
- [ ] API keys are read with `podcast_tts.config.get_key` and never printed, logged or included
      in exception messages.
- [ ] Errors are raised as `EngineError` with an actionable message.
- [ ] Tests mock the network (see `tests/test_cloud_engines.py`, which patches
      `urllib.request.urlopen`) and the entry points (see `tests/test_engine_registry.py`).
