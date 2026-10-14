# Contributing to AudioGeneration

Thanks for your interest in improving AudioGeneration. Bug reports, documentation fixes, new
engines and features are all welcome. Issues and pull requests can be written in English or
Spanish.

## Development setup

You need Windows 10/11 (the target platform; Linux works for the core and the tests),
[uv](https://docs.astral.sh/uv/), Git and `ffmpeg` in the `PATH`. uv installs Python 3.11 for you.

```powershell
git clone https://github.com/enriquevelmai/AudioGeneration.git
cd AudioGeneration

# Core only (no torch): parser, dummy engine, CLI, UI, models command and fast tests
uv sync --extra dev

# Everything, with the local engines on an NVIDIA GPU (several GB)
uv sync --extra local --extra cuda --extra desktop --extra dev

# ...or on CPU
uv sync --extra local --extra cpu --extra desktop --extra dev
```

`bats\install.bat` does the same with GPU detection and extra checks. Use
`.venv\Scripts\python.exe scripts\check_env.py` to diagnose the environment (it should end with
`ALL OK`).

Set these environment variables in your shell (the `.bat` scripts already do it):

```powershell
$env:PYTHONUTF8 = '1'         # avoids UnicodeEncodeError in the Windows console
$env:COQUI_TOS_AGREED = '1'   # XTTS v2 would otherwise wait for license confirmation
```

### Dependencies

- Change dependencies only in `pyproject.toml`, then run `uv lock --python 3.11` and
  `uv sync --extra ...`. Do not `pip install` packages into `.venv`.
- Keep `torch` / `torchaudio` at 2.8: from 2.9 they use torchcodec, which fails on Windows without
  the shared FFmpeg DLLs. Keep `transformers` below 5 (it breaks coqui-tts). Details in
  [docs/ENGINES.md](docs/ENGINES.md).
- The core must not import torch. `scripts/check_env.py` checks it.

## Tests

```powershell
uv run pytest            # fast tests (~10 s): dummy engine, no GPU, no models
uv run pytest -m slow    # real F5-TTS / XTTS v2 synthesis: needs the local extra, the models and ideally a GPU (~40 s)
```

`pytest` excludes the `slow` marker by default (see `pyproject.toml`). CI runs the fast tests on
Ubuntu and Windows with the core only, so new fast tests must not need torch, model weights,
network access or API keys: use the `dummy` engine and mock `urllib.request.urlopen` for cloud
engines (see `tests/test_cloud_engines.py`).

## Style

- Python 3.11, type hints, `from __future__ import annotations`, small functions and docstrings for
  public APIs. Follow the style of the surrounding code.
- Heavy imports (torch, f5_tts, TTS) go inside functions, so the CLI, the UI and `engines` start fast
  and the core works without them.
- **English is the project language**: code identifiers, comments, docstrings, documentation and
  the default user-facing messages (CLI help, errors, warnings and UI labels) are in English.
- **Spanish is available as a UI/CLI language** (`PODCAST_TTS_LANG=es` or Settings → Language).
  Every new user-facing string must go through the i18n module (`podcast_tts.i18n`) with an entry
  in both English and Spanish; do not hard-code messages in either language.
- README.es.md is the full Spanish translation of README.md: keep it in sync whenever user-facing
  behaviour changes.
- Never print, log or include API keys in exceptions. Read them with `podcast_tts.config.get_key`.
- Do not commit `output/`, `.cache/`, `.venv/`, `.env` or model weights.
- Commit messages are written in English and follow
  [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`,
  `ci:`, `chore:`...).

## Adding a TTS engine

The preferred way is an **independent plugin package** discovered through the
`podcast_tts.engines` entry point group: it needs no change in this repository. The full guide,
with the engine protocol, `LicenseInfo` and a complete example, is in
[docs/ENGINES_PLUGINS.md](docs/ENGINES_PLUGINS.md).

To add a built-in engine instead, put it in `src/podcast_tts/engines/`, register it in
`src/podcast_tts/engines/__init__.py`, declare an accurate `license_info`, add tests and document
it in the README and in [MODELS_AND_LICENSES.md](MODELS_AND_LICENSES.md). Engines whose model or
service license is unclear will not be merged.

## Pull requests

1. Create a branch from `main`.
2. Make the change, with tests and documentation (README.md **and** README.es.md when user-facing
   behaviour changes, and English and Spanish i18n entries for any new user-facing string).
3. Add an entry under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).
4. Run `uv run pytest` (and `uv run pytest -m slow` if you touched engines or audio).
5. Open the pull request and fill in the template.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
