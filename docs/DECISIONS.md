# Technical decision log

Design decisions of AudioGeneration (`podcast_tts`) and the reasons behind them. For version and pin
details, see [ENGINES.md](ENGINES.md); for licenses, [MODELS_AND_LICENSES.md](../MODELS_AND_LICENSES.md).

## Scope

- **Platform**: Windows 10/11 x64, Python 3.11 managed by uv, ffmpeg on the `PATH`. NVIDIA GPU
  recommended; the CPU works as a slower alternative. Reference environment: Windows 11 with a
  16 GB RTX 4080 SUPER.
- **Script format**: Markdown with inline tags, e.g.
  `[voice:ana] Hello. [pause:1.5] [voice:carlos lang=es] Hola. [music:intro.mp3 vol=0.3]`. It is
  readable plain text, easy to version and to write by hand or with an assistant.
- **Interface**: CLI and local web UI with Gradio, in English by default (Spanish optional, see
  [Language](#language)). The desktop app (`podcast-tts desktop`, `desktop` extra) shows the same UI
  in a native window with pywebview.
- **Claude Code skill**: versioned in `skill/podcast-tts/` and installed as a junction in
  `~/.claude/skills/podcast-tts` (see [SKILL.md](SKILL.md)). It is optional.
- **Sample voices** generated automatically in `voices/`; users add their own.
- **No Edge-TTS**: the unofficial Microsoft Edge read-aloud endpoint (`edge-tts`) and the system SAPI
  voices are not used. Microsoft's official option is the `azure` engine (paid Azure AI Speech, with
  your own key).

## Language

- **English is the primary language** of the documentation, the CLI and the UI. Spanish is available
  through [README.es.md](../README.es.md) (full translation) and as an optional UI language
  (`PODCAST_TTS_LANG=es`, or Settings -> Language).
- **Script tags**: the English tags (`[voice:]`, `[pause:]`, `[music:]`, `[sfx:]`, `[title:]`) are
  canonical; the Spanish tags (`[voz:]`, `[pausa:]`, `[musica:]`, `[titulo:]`...) are kept as aliases,
  so existing scripts keep working.

## Local engines

- **F5-TTS by default, one F5 model per language**: `lang=en` uses the official `F5TTS_v1_Base` model;
  `lang=es` uses the community finetune `jpgallegoar/F5-Spanish` (`F5TTS_Base` architecture,
  CC-BY-NC-4.0), because the base model (English/Chinese) pronounces Spanish with an accent. Other
  languages → XTTS v2.
- **torch pinned to 2.8** (`torch==2.8.*`, `torchaudio==2.8.*`, cu126): since 2.9 `torchaudio.load`
  delegates to torchcodec, which on Windows needs the shared FFmpeg DLLs (the usual ffmpeg builds are
  static) and breaks F5 and XTTS.
- **transformers < 5**: coqui-tts 0.27 imports a function removed in transformers 5.
- **A single `.venv`** for F5-TTS and coqui-tts: they coexist with the pins above.
- **Sample voices** (`ana`, `carlos`, `emma`, `david`) generated with built-in XTTS speakers
  (`scripts/make_sample_voices.py`), so there is no dependency on external recordings. They inherit
  the non-commercial license of XTTS v2.
- **Synthesis cache** in `.cache/tts/<sha256>.npz` (key: text, voice fingerprint, language, speed,
  engine). When the script is edited, only the changed sentences are synthesized again.
- **Seed `None` by default**: F5 and XTTS sample, so each synthesis is a different take; a
  regeneration is identical only thanks to the cache (`--no-cache` gives a new take).

## Layered installation

- **Core without torch** (parser, `dummy` engine, CLI, UI, `models`, fast tests) plus uv extras:
  `local` (F5-TTS and XTTS v2), `cuda` / `cpu` (PyTorch variant, mutually exclusive), `dev`
  (pytest) and `desktop` (pywebview). CI installs only the core.
- **`uv.lock` for everything**: `bats\install.bat` installs uv and Python 3.11 without administrator
  rights and runs `uv sync --locked`; the chosen extras are saved in `.venv\podcast-tts-extras.txt` so
  that `bats\update.bat` reuses them.
- **Automatic device**: `cuda` if PyTorch sees a GPU, otherwise `cpu`; `PODCAST_TTS_DEVICE` forces
  it.
- **Models outside the repository**: they are downloaded from Hugging Face to the standard caches
  (HF and coqui) the first time or with `podcast-tts models download`; `models update` fetches the
  latest revision.

## Cloud engines, plugins and licenses

- **Explicit licenses**: each engine declares `license_info` (`LicenseInfo`). The CLI warns once when
  generating with a non-commercial engine (`--no-license-notice` hides it) and the UI shows a discreet
  notice. Plugins that do not declare a license are treated as non-commercial.
- **Paid cloud engines** (`elevenlabs`, `azure`, `openai`) using only the standard library
  (`urllib.request`) and requesting 24 kHz PCM directly; no SDKs and no new dependencies.
- **Keys** in environment variables or in `.env` (ignored by git); environment variables take
  precedence. They are never printed: they are shown masked (`sk-...abcd`).
- **Third-party plugins** via entry points in the `podcast_tts.engines` group; the valid engine names
  are dynamic (`engines.engine_names()`). See [ENGINES_PLUGINS.md](ENGINES_PLUGINS.md).
- **Cloud voices**: `voice.json` with `provider_voice_id` and `provider_options`, without `ref.wav`. The
  cache fingerprint only changes for voices that have those fields (local voices keep their cache).
- Commercial use details: [COMMERCIAL_USE.md](COMMERCIAL_USE.md).

## Distribution (1.0.0)

- **Windows release**: `AudioGeneration-v1.0.0-windows.zip` with the code, the `bats\` scripts and
  the `AudioGeneration.exe` launcher (built with `bats\build_launcher.bat`). It does not include
  `.venv` or models: the launcher installs the environment on first run.
- **Updates from the launcher**: in a git clone it checks for changes with git; in a zip download it
  queries the latest GitHub release.
- **Startup**: `bats\run.bat` opens the desktop app and, if pywebview is missing, falls back to the
  browser; `bats\run_web.bat` always opens the browser. `bats\create_shortcuts.bat` creates the
  Desktop and Start menu shortcuts (offered by `bats\install.bat`).
- **License**: the code is MIT; the model weights keep their own licenses.

## Robustness and security (post-1.0.0 review)

- **Paths with accents**: Python 3.11 reads `.pth` files with the Windows ANSI code page even with
  `PYTHONUTF8=1`, so uv's editable install failed in `C:\Users\José\...`. `uv sync --no-editable`
  was ruled out because the code locates the project with `Path(__file__).parents[2]` (voices,
  examples, `.env`) and it would force reinstalling the package on every update. Instead,
  `scripts/fix_editable_pth.py` rewrites the `.pth` as an ASCII-only `import` line that computes
  `<project>\src` from `sys.prefix`; the `.bat` files and the launcher also set `PYTHONPATH`.
- **Remote UI**: outside `127.0.0.1` or with `--share` the UI requires `--auth` and runs in remote
  mode (no Settings tab and no absolute audio paths). Internal events are private in the Gradio
  API (`api_visibility="private"`).
- **Synthesis cache**: the key includes each engine's `cache_tag` (model, package version and
  parameters), so switching models regenerates the sentences.
- **Single instance**: the mutex includes a hash of the project folder (several installations can
  coexist) and the launcher checks it so it does not update while the app is open.
