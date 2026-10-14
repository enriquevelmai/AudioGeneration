# Commercial use

> **You are responsible for complying with the license and terms of every model and provider
> you use.** This document is a practical summary, not legal advice. Licenses and provider
> terms change: always read the current version linked below before publishing audio.

The code of this project is MIT, but **the default local models are non-commercial**. The full
list of models and services, with their licenses and where they are cached, is in
[MODELS_AND_LICENSES.md](../MODELS_AND_LICENSES.md).

## Which engines allow commercial use?

| Engine | Type | License of the audio source | Commercial use |
|---|---|---|---|
| `f5` | local (GPU) | F5-TTS weights (`F5TTS_v1_Base`) and `jpgallegoar/F5-Spanish`: **CC-BY-NC-4.0** | **No** |
| `xtts` | local (GPU) | XTTS v2 weights: **[Coqui Public Model License (CPML)](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt)**; when you share the audio, include a link to the CPML | **No** |
| `dummy` | local | No model (test tones) | Yes (but it is not speech) |
| `elevenlabs` | cloud (paid API) | [ElevenLabs Terms](https://elevenlabs.io/terms-of-use) | Depends on the plan: paid plans yes; the free plan is non-commercial and requires attribution |
| `azure` | cloud (paid API) | [Microsoft Product Terms](https://www.microsoft.com/licensing/terms/productoffering/MicrosoftAzure) for Azure AI Speech | Yes, with your own Azure subscription, subject to Microsoft's terms and the Azure AI Speech code of conduct |
| `openai` | cloud (paid API) | [OpenAI Terms and policies](https://openai.com/policies/) | Yes, subject to OpenAI's terms; its usage policies require disclosing to listeners that the voice is AI-generated |
| third-party plugins | — | Declared by each plugin (`license_info`) | See `python -m podcast_tts engines`; plugins that declare nothing are treated as non-commercial |

Notes:

- The **code** of F5-TTS (MIT) and coqui-tts (MPL-2.0) is permissive, but the **model
  weights** used to generate the audio are not. What matters for the audio you publish is the
  weights' license.
- Coqui (the company) shut down and no longer sells commercial XTTS licenses.
- The **sample voices** in `voices/` (`ana`, `carlos`, `emma`, `david`) were generated with
  built-in XTTS v2 speakers, so they are non-commercial too, even with another engine. For
  commercial work use your own (consented) recordings or cloud voices.
- If you need a local, offline engine for commercial work, write a plugin around a model whose
  weights have a permissive license (see [ENGINES_PLUGINS.md](ENGINES_PLUGINS.md)) and declare
  it accurately in `license_info`.
- The project does not use Edge-TTS. The `azure` engine uses the official, paid Azure AI Speech
  REST API with your own resource key; it has nothing to do with the free, unofficial Edge
  read-aloud endpoint.
- Check the current status at any time:

  ```powershell
  python -m podcast_tts engines          # table: type, commercial use, status, license
  python -m podcast_tts engines --json   # same data, machine readable
  ```

When a script is generated with a non-commercial engine, the CLI prints a short license notice
once (hide it with `--no-license-notice`) and the UI shows a discreet notice in the generation
tab.

## Voice cloning and consent

Cloning or imitating someone else's voice (with F5/XTTS reference clips, ElevenLabs voice
cloning, or any other method) **requires that person's explicit consent**, and in many
jurisdictions it is also regulated by personality, image and data-protection laws. Only clone
your own voice or voices you have written permission to use, and follow each provider's
policies on voice cloning and on disclosing synthetic audio.

## Setting up the cloud engines

All cloud engines use only the Python standard library (no extra dependencies), request raw
PCM directly from the API (mono, 24 kHz) and never print or log your keys.

API keys are read, in this order, from:

1. environment variables (`ELEVENLABS_API_KEY`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`,
   `OPENAI_API_KEY`);
2. the `.env` file at the project root (ignored by git; see `.env.example`).

Three ways to store a key in `.env`:

- CLI (the value is asked for without echo; it is never passed as an argument):

  ```powershell
  python -m podcast_tts config set OPENAI_API_KEY
  python -m podcast_tts config show            # masked values, e.g. sk-...abcd
  python -m podcast_tts config unset OPENAI_API_KEY
  ```

- UI: tab **Ajustes** → choose the variable, paste the key, **Guardar clave**.
- Manually: copy `.env.example` to `.env` and fill in the values.

Cloud voices do not need a `ref.wav`: they point to a voice of the provider with
`provider_voice_id` and, optionally, `provider_options` (stored in `voices/<name>/voice.json`).

### ElevenLabs

1. Create an account at <https://elevenlabs.io> and choose a plan that allows commercial use.
2. Create an API key (Settings → API Keys) and store it:
   `python -m podcast_tts config set ELEVENLABS_API_KEY`.
3. Pick a voice in the Voice Library or your own (consented) voice and copy its **voice ID**.
4. Register it:

   ```powershell
   python -m podcast_tts voices add lucia --engine elevenlabs --provider-voice-id <VOICE_ID> --lang es
   ```

   Optional `--provider-option` values (repeatable; JSON values allowed):
   `model_id=eleven_turbo_v2_5` (default `eleven_multilingual_v2`),
   `voice_settings={"stability":0.5,"similarity_boost":0.8}`, `language_code=es`, `seed=42`.

Details: `POST /v1/text-to-speech/{voice_id}?output_format=pcm_24000` with the `xi-api-key`
header. `speed` is sent as `voice_settings.speed` (the API accepts 0.7–1.2; values are clamped).
`language_code` is only sent automatically to models that support it (`eleven_turbo_v2_5`,
`eleven_flash_v2_5`).

### Azure AI Speech

1. In the Azure portal create a **Speech** resource (Azure AI services) on a paid tier.
2. Copy one of its **keys** and its **region** (e.g. `westeurope`) and store them:

   ```powershell
   python -m podcast_tts config set AZURE_SPEECH_KEY
   python -m podcast_tts config set AZURE_SPEECH_REGION
   ```

3. Choose a neural voice from the
   [voice gallery](https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts),
   e.g. `es-ES-AlvaroNeural`, `es-ES-ElviraNeural`, `en-US-JennyNeural`.
4. Register it:

   ```powershell
   python -m podcast_tts voices add alvaro --engine azure --provider-voice-id es-ES-AlvaroNeural --lang es
   ```

   Optional `--provider-option` values: `style=cheerful`, `style_degree=1.5`, `role=...`,
   `pitch=+5%`, `xml_lang=es-MX`.

Details: `POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1` with the
`Ocp-Apim-Subscription-Key` header, an SSML body (`xml:lang` + voice name, `prosody rate` for
`speed`) and `X-Microsoft-OutputFormat: raw-24khz-16bit-mono-pcm`. For multilingual voices
(`...MultilingualNeural`) a segment in another language is wrapped in `<lang xml:lang=...>`.

### OpenAI

1. Create an API key at <https://platform.openai.com/api-keys> (billing must be enabled) and
   store it: `python -m podcast_tts config set OPENAI_API_KEY`.
2. Choose a built-in voice: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`,
   `sage`, `shimmer`, `verse`.
3. Register it:

   ```powershell
   python -m podcast_tts voices add nova --engine openai --provider-voice-id nova --lang es
   ```

   Optional `--provider-option` values: `model=tts-1-hd` (default `gpt-4o-mini-tts`),
   `instructions="Warm, calm tone"` (style instructions, `gpt-4o-*-tts` models only).

Details: `POST https://api.openai.com/v1/audio/speech` with `response_format=pcm`
(24 kHz, 16-bit little-endian) and `speed` (0.25–4.0). Remember to tell your audience that the
voices are AI-generated.

### Errors

HTTP errors are reported in Spanish with the provider's message (keys are always redacted):
401 invalid key, 402/403 plan or permission problems, 404 wrong voice/model/region, 429 rate
limit or quota. 429 and 5xx responses and network errors are retried twice with exponential
backoff (honoring `Retry-After`).

## Choosing the engine per voice or per script

The engine used for each sentence is resolved with this priority:

1. `--engine` in the CLI (or the "Motor" selector in the UI) — forces one engine for the whole
   script;
2. the `engine=` attribute of a voice tag: `[voz:ana engine=openai]`;
3. the script front matter: `engine: azure`;
4. the voice's own `engine` in `voice.json`;
5. the default (`f5`).

So the simplest commercial setup is to create cloud voices (their `voice.json` already says
`engine: openai`, `azure` or `elevenlabs`) and use them in your scripts:

```markdown
---
title: My commercial episode
lang: es
---
[voz:alvaro] Bienvenidos al episodio.
[voz:nova] Hoy hablamos de...
```

Be careful when mixing: if a script uses one local voice (`f5`/`xtts`) next to cloud voices,
that part of the audio is still non-commercial. Forcing a cloud engine with `--engine` only
works if every voice in the script has a `provider_voice_id` valid for that provider.

## Summary checklist before publishing

- [ ] Every sentence was generated with an engine whose license allows commercial use
      (`python -m podcast_tts engines`; no license notice when generating).
- [ ] Your provider plan allows commercial use, and you follow its terms and usage policies.
- [ ] No sample voice from `voices/` (they are non-commercial XTTS output) is used.
- [ ] You have consent for every cloned or imitated voice.
- [ ] You disclose AI-generated voices where the provider or the law requires it.
- [ ] Background music and sound effects are also licensed for your use.
