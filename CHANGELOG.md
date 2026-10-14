# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- The UI refuses to start with `--host` other than loopback or with `--share` unless
  `--auth user:password` (or `PODCAST_TTS_AUTH`) is set. In that remote mode the Ajustes tab is
  hidden and music/sfx paths must be relative; internal events are private in the Gradio API.
- `[voz:../x]` can no longer read outside `voices/`; Windows reserved names (CON, NUL...) are
  rejected as voice names. The launcher only opens release URLs of this repository.

### Fixed

- Installing into a folder with accents or `ñ` (e.g. `C:\Users\José\...`) now works: the
  editable install's `.pth` is rewritten as ASCII after `uv sync`, and the launcher and the `.bat`
  scripts also set `PYTHONPATH`.
- The `.bat` scripts work in folders with `&`, `!`, `( )`, `[ ]` or spaces, check that they run
  from an extracted project, and `update.bat` returns an error (shown by the launcher) when
  `git pull` fails. The `.ps1` scripts use `-LiteralPath`.
- Loudness normalization now reaches the target (±0.5 LU) instead of ending ~1.5 LU lower
  because of the peak limit.
- Multi-line HTML comments are no longer read aloud; Markdown links and checkboxes are plain
  text; `lang: no` stays `"no"`; `nan`, `inf` and huge pauses or fades are rejected.
- A malformed `voice.json` no longer breaks the voice list; clearer errors without ffmpeg.
- The synthesis cache depends on the model version and parameters of each engine.
- The launcher no longer offers to update while the app is open, detects when the app dies at
  startup, and each installation has its own single-instance lock and log.
- `.env` values in quotes followed by a comment are read correctly.

### Changed

- The release zip contains an `AudioGeneration/` folder. `install.bat /y` also creates the
  shortcuts (`/noshortcuts` to skip them) and installs the `dev` extra only with `/dev`.
- The example `guiones/ejemplo_dialogo.md` moved to `examples/`; `guiones/` (where the app saves
  your scripts) is ignored by git.
- In the browser mode without a console, a small window lets you reopen the browser or close
  AudioGeneration.

## [1.0.0] - 2026-10-14

First public release.

### Added

#### Scripts and audio

- Markdown script format with optional front matter (`title`, `lang`, `default_voice`, `engine`,
  `paragraph_pause`) and inline tags: `[voz:...]` with `lang=`, `speed=` and `engine=` attributes,
  `[pausa:N]`, `[musica:...]` (inserted clips, looping background music with ducking,
  `[musica:stop]`), `[sfx:...]` and `[titulo:...]`. English aliases (`[voice:]`, `[pause:]`,
  `[music:]`) are accepted.
- Comment lines (`#` and `<!--`), sentence-aware chunking (`--max-chars`), quoted paths with spaces,
  and parse errors that point to the line number.
- Assembler with resampling, paragraph pauses, music fades, loudness normalization to -16 LUFS
  (configurable) and MP3 or WAV export.
- Synthesis cache (`.cache/tts`): when a script is edited, only the changed sentences are generated
  again.

#### Engines

- **F5-TTS** (default) for voice cloning from a short clip: the official `F5TTS_v1_Base` model for
  English and the `jpgallegoar/F5-Spanish` fine-tune for Spanish.
- **XTTS v2** (Coqui) with 17 languages, voice cloning and 58 built-in speakers.
- **Cloud engines**: ElevenLabs, Azure AI Speech and OpenAI text-to-speech, using only the Python
  standard library, with retries, clear errors and keys that are never printed.
- `dummy` engine that produces tones, to check timing and mixing without models or a GPU.
- Third-party engine plugins through the `podcast_tts.engines` entry point group.
- License metadata for every engine (`LicenseInfo`), `podcast-tts engines` overview, and a license
  notice when a script uses a non-commercial engine.
- Automatic device selection (CUDA GPU or CPU), overridable with `PODCAST_TTS_DEVICE`.

#### Voices

- Voice registry in `voices/<name>/` (`ref.wav`, `ref.txt`, `voice.json`) with `voices list`,
  `voices add` and `voices remove`. Clips in any format ffmpeg can read are converted
  automatically.
- Automatic transcription of reference clips with Whisper when `ref.txt` is missing.
- Voices based on XTTS built-in speakers and cloud voices (`provider_voice_id`,
  `provider_options`).
- Four sample voices: `ana` and `carlos` (Spanish), `emma` and `david` (English).

#### Applications

- Command line `podcast-tts` (also `python -m podcast_tts`) with the `generate`, `parse`, `voices`,
  `engines`, `config`, `models`, `ui` and `desktop` commands. Messages are in Spanish.
- Web UI (Gradio, in Spanish) with the **Guion → Podcast**, **Voces**, **Sistema** and **Ajustes**
  tabs: script editor with validation and progress, voice preview, recording and cloning, system
  status, API keys and engine licenses.
- Desktop app (`podcast-tts desktop`, `desktop` extra) that shows the UI in a native window with
  pywebview.
- API key management in `.env` with `podcast-tts config` or the **Ajustes** tab.
- Model management with `podcast-tts models list|status|download|update`. Models are downloaded from
  Hugging Face on first use and are never stored in the repository.
- Optional `podcast-tts` skill for Claude Code, with portable PowerShell and Bash wrappers.

#### Installation and distribution

- `bats\install.bat`: installs uv, Python 3.11 and a locked `.venv`, detects an NVIDIA GPU (PyTorch
  CUDA 12.6 or CPU), offers to install ffmpeg, download the models, create shortcuts and install the
  Claude Code skill.
- `bats\run.bat` (desktop app, falls back to the browser without pywebview), `bats\run_web.bat`
  (browser), `bats\update.bat` (code, dependencies and models), `bats\install_gpu.bat` (switch from
  CPU to CUDA), `bats\create_shortcuts.bat` (Desktop and Start menu shortcuts) and
  `bats\build_launcher.bat`.
- `AudioGeneration.exe` launcher: installs on first run, checks for updates (git in a clone, the
  latest GitHub release in a zip download) and opens the app.
- Windows release asset `AudioGeneration-v1.0.0-windows.zip`.
- Layered dependencies with uv extras: a torch-free core plus `local`, `cuda` / `cpu`, `desktop`
  and `dev`.

#### Project

- MIT license for the code, [MODELS_AND_LICENSES.md](MODELS_AND_LICENSES.md) and
  [docs/COMMERCIAL_USE.md](docs/COMMERCIAL_USE.md).
- README in English and Spanish, contributing guide, documentation index.
- Continuous integration on Ubuntu and Windows (core only), issue and pull request templates.
- Example scripts in Spanish, English and a bilingual dialogue.

[Unreleased]: https://github.com/enriquevelmai/AudioGeneration/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/enriquevelmai/AudioGeneration/releases/tag/v1.0.0
