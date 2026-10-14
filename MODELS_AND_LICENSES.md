# Models and licenses

**TL;DR**

- The **code** of AudioGeneration is [MIT](LICENSE). That license covers this repository's source
  code only.
- The **default local voice models are NOT licensed for commercial use**: XTTS v2 (Coqui Public
  Model License) and F5-TTS / F5-Spanish (CC-BY-NC-4.0). Audio produced with them can only be used
  for non-commercial purposes.
- For **commercial use**, generate with an engine whose license allows it: ElevenLabs on a paid
  plan, Azure AI Speech (paid), OpenAI, or your own plugin backed by a permissively licensed model.
- **Cloning a voice requires the consent of the person it belongs to.**

> This document is a practical summary, **not legal advice**. Licenses and provider terms change
> over time. Each user is responsible for reading and complying with the current license and terms
> of every model, service, voice, music file and sound effect they use.

## Models are not included in this repository

No model weights are stored in git or in the release zip. They are downloaded from
[Hugging Face](https://huggingface.co) on your machine:

- **automatically**, the first time an engine needs them; or
- **in advance**, with `podcast-tts models download` (all required models) or
  `podcast-tts models download <name>`.

Keep them up to date with `podcast-tts models update` (only the models you already have) or
`bats\update.bat`, which also updates the code and the dependencies.
`podcast-tts models list` shows each model's repository, size and license, and
`podcast-tts models status` shows whether it is downloaded, where, and how much space it uses.

Downloading a model means accepting its license. For XTTS v2 the program sets
`COQUI_TOS_AGREED=1`, which accepts the CPML (non-commercial) on your behalf, so make sure you
agree with it before using the `xtts` engine.

## Local models

| Name (`models`) | Repository | Used by | License | Commercial use | Auto-download | Cache location |
|---|---|---|---|---|---|---|
| `f5-base` | [SWivid/F5-TTS](https://huggingface.co/SWivid/F5-TTS) (`F5TTS_v1_Base`) | `f5`, English | [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/) (weights; the [F5-TTS code](https://github.com/SWivid/F5-TTS) is MIT) | **No** | Yes (~1.3 GB) | Hugging Face cache |
| `f5-spanish` | [jpgallegoar/F5-Spanish](https://huggingface.co/jpgallegoar/F5-Spanish) | `f5`, Spanish | [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/) | **No** | Yes (~1.3 GB) | Hugging Face cache |
| `vocos` | [charactr/vocos-mel-24khz](https://huggingface.co/charactr/vocos-mel-24khz) | `f5` (vocoder, all languages) | MIT | Yes | Yes (~54 MB) | Hugging Face cache |
| `xtts` | [coqui/XTTS-v2](https://huggingface.co/coqui/XTTS-v2) | `xtts` (17 languages, 58 built-in speakers) | [Coqui Public Model License (CPML)](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt) | **No** | Yes (~1.9 GB) | `%LOCALAPPDATA%\tts\tts_models--multilingual--multi-dataset--xtts_v2` |
| `whisper` (optional) | [openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | `f5`, only to transcribe a voice clip that has no `ref.txt` | MIT | Yes | Only when needed (~1.6 GB) | Hugging Face cache |

Why the F5 weights are non-commercial even though the F5-TTS code is MIT: the released
checkpoints were trained on data (the Emilia dataset, among others) whose license does not allow
commercial use, so the authors publish the weights under CC-BY-NC-4.0. The Spanish fine-tune
inherits that restriction. Coqui, the company behind XTTS v2, has shut down and no longer sells
commercial CPML licenses.

The CPML also requires that anyone you give the XTTS v2 model **or its output** (for example, the
audio files you generate) receives a copy of the CPML terms or a link to them
(<https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt>), together with the notice that the model is licensed under the
CPML. If you share audio made with `xtts`, include that link in the description or credits.

### Cache locations

| Cache | Default path (Windows) | Override |
|---|---|---|
| Hugging Face cache | `%USERPROFILE%\.cache\huggingface\hub` | `HF_HOME` or `HF_HUB_CACHE` |
| coqui-tts models (XTTS v2) | `%LOCALAPPDATA%\tts` | `TTS_HOME` (or `XDG_DATA_HOME`) |

To remove the models, delete the corresponding `models--...` folders (Hugging Face cache) and the
`tts_models--multilingual--multi-dataset--xtts_v2` folder. They will be downloaded again if needed.

## Cloud services

Cloud engines download nothing: text is sent to the provider's API and the audio comes back. You
need your own account and API key (see [docs/COMMERCIAL_USE.md](docs/COMMERCIAL_USE.md)).

| Engine | Service | Terms | Commercial use | Auto-download | Cache location |
|---|---|---|---|---|---|
| `elevenlabs` | [ElevenLabs API](https://elevenlabs.io) | [ElevenLabs Terms](https://elevenlabs.io/terms-of-use) | **Paid plans: yes.** Free plan: no (and requires attribution) | No (API) | Only the project's synthesis cache (`.cache/tts`) |
| `azure` | [Azure AI Speech](https://azure.microsoft.com/products/ai-services/ai-speech) (official REST API, your own resource) | [Microsoft Product Terms](https://www.microsoft.com/licensing/terms/productoffering/MicrosoftAzure) and the Azure AI Speech code of conduct | Yes, with a paid Azure subscription | No (API) | Only `.cache/tts` |
| `openai` | [OpenAI text-to-speech API](https://platform.openai.com/docs/guides/text-to-speech) | [OpenAI terms and policies](https://openai.com/policies/) | Yes, subject to OpenAI's terms; listeners must be told the voice is AI-generated | No (API) | Only `.cache/tts` |

The `azure` engine is the official, paid Azure AI Speech service. This project does not use the
unofficial Edge "read aloud" endpoint (`edge-tts`).

## Other engines

| Engine | What it is | Commercial use |
|---|---|---|
| `dummy` | Built-in test engine that produces tones instead of speech (no model) | Yes, but it is not speech |
| Third-party plugins | Engines installed as Python packages ([docs/ENGINES_PLUGINS.md](docs/ENGINES_PLUGINS.md)) | Whatever the plugin declares in `license_info`. Plugins that declare nothing are treated as **non-commercial** |

`podcast-tts engines` prints the type, license, commercial-use status and configuration of every
engine installed, built-in or plugin.

## Sample voices in `voices/`

The four sample voices (`ana`, `carlos`, `emma`, `david`) were generated with **built-in XTTS v2
speakers** (`scripts/make_sample_voices.py`). Their reference clips are XTTS output, so they
**inherit the CPML non-commercial restriction**, whichever engine you later use them with. For
commercial work, record your own voice (or a voice you have written permission to use) or use a
cloud voice.

## Voice cloning and consent

Cloning or imitating someone's voice, with a reference clip for F5/XTTS, with ElevenLabs voice
cloning or any other method, **requires that person's explicit consent**. In many jurisdictions
voice cloning is also covered by personality, image and data-protection law. Only clone your own
voice or voices you are authorized to use, follow each provider's voice-cloning policies, and
disclose synthetic audio where the provider or the law requires it.

## Python dependencies

The program depends on open-source Python packages, installed by `uv` from PyPI and the PyTorch
index (they are not redistributed in this repository). The main ones: `f5-tts` (MIT),
`coqui-tts` (MPL-2.0), `torch` / `torchaudio` (BSD-3-Clause), `transformers` and `gradio`
(Apache-2.0), `numpy` and `scipy` (BSD-3-Clause), `pydub` (MIT), `huggingface-hub` (Apache-2.0).
The optional desktop app (`desktop` extra) uses `pywebview` (BSD-3-Clause). `ffmpeg`, which the
installer can install with `winget`, is a separate program under its own LGPL/GPL license.

## How the program helps you stay compliant

- Every engine declares its license (`LicenseInfo`) and `podcast-tts engines` shows it.
- When a script uses a non-commercial engine, `podcast-tts generate` prints a license notice
  (hide it with `--no-license-notice`) and the app shows a discreet notice in the generation tab.
- The **Ajustes** (settings) tab of the app lists every engine with its license and whether it
  allows commercial use.

Before publishing audio commercially, go through the checklist in
[docs/COMMERCIAL_USE.md](docs/COMMERCIAL_USE.md#summary-checklist-before-publishing).
