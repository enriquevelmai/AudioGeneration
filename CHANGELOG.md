# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-14

First public release.

### Added

#### Scripts and audio

- Markdown script format with optional front matter (`title`, `lang`, `default_voice`, `engine`,
  `paragraph_pause`) and inline tags: `[voice:...]` with `lang=`, `speed=` and `engine=`
  attributes, `[pause:N]`, `[music:...]` (inserted clips, looping background music with ducking,
  `[music:stop]`), `[sfx:...]` and `[title:...]`.
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
  `engines`, `config`, `models`, `ui`, `desktop` and `mcp` commands.
- Web UI (Gradio) with the **Script → Podcast**, **Voices**, **System** and **Settings**
  tabs: script editor with validation and progress, voice preview, recording and cloning, system
  status, API keys and engine licenses.
- Desktop app (`podcast-tts desktop`, `desktop` extra) that shows the UI in a native window with
  pywebview.
- API key management in `.env` with `podcast-tts config` or the **Settings** tab.
- Model management with `podcast-tts models list|status|download|update`. Models are downloaded from
  Hugging Face on first use and are never stored in the repository.
- Optional `podcast-tts` skill for Claude Code, with portable PowerShell and Bash wrappers.

#### AI assistants (MCP)

- MCP server over stdio (`podcast-tts mcp`, `python -m podcast_tts mcp` or `podcast-tts-mcp`,
  `mcp` extra) built with the official Python SDK, so any MCP client (Claude Desktop, Claude Code,
  Cursor, VS Code...) can turn "make me a podcast about X" into an MP3. Tools: `list_voices`,
  `list_engines`, `get_script_format`, `validate_script` (errors with line numbers, missing voices,
  estimated duration), `generate_podcast`, `generate_podcast_from_file`, `get_generation_status`,
  `synthesize_text`, `add_voice`, `list_outputs` and `open_output_folder`, plus a `podcast` prompt
  and a `podcast-tts://script-format` resource.
- Per-segment progress notifications; generations longer than 45 s return a job id that the
  assistant polls, so client timeouts are never hit. Output in `output/` or
  `PODCAST_TTS_OUTPUT_DIR`, validated output names, music/sfx paths restricted like the remote UI,
  and stdout reserved for the protocol (library output goes to stderr).
- `bats\install_integrations.bat` (`scripts/install_integrations.py`): idempotent registration in
  Claude Code (skill + `claude mcp add --scope user`) and Claude Desktop (merges
  `claude_desktop_config.json` with a `.bak` backup), JSON for other clients (`/print`),
  `--uninstall`, `--dry-run` and `--config-path` for testing.
- The `podcast-tts` skill now covers the end-to-end "make me a podcast about X" flow (defaults,
  research, podcast structure, ~150 words per minute) and prefers the MCP tools when available.
- Reference: `docs/MCP.md`.

#### Languages

- English is the primary language: documentation, CLI help and messages, UI labels and default
  messages. The UI and CLI are also available in Spanish with `PODCAST_TTS_LANG=es` or under
  **Settings → Language**; `README.es.md` is a full Spanish translation of the README.
- English script tags are canonical (`[voice:]`, `[pause:]`, `[music:]`, `bg`, `[music:stop]`,
  `[title:]`); the Spanish tags (`[voz:]`, `[pausa:]`, `[musica:]`, `fondo`, `[titulo:]`) are
  accepted as aliases.

#### Security

- The UI listens on `127.0.0.1` by default and refuses to start with another `--host` or with
  `--share` unless `--auth user:password` (or `PODCAST_TTS_AUTH`) is set. In that remote mode the
  Settings tab is hidden, music/sfx paths must be relative and internal events are private in
  the Gradio API.
- API keys are never printed, logged or cached; voice names cannot escape `voices/` and Windows
  reserved names are rejected; the launcher only opens release URLs of this repository.

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

[1.0.0]: https://github.com/enriquevelmai/AudioGeneration/releases/tag/v1.0.0
