## What does this change?

<!-- A short description of the change and why it is needed. Link the issue if there is one: "Closes #123". -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] New engine or plugin support
- [ ] Documentation
- [ ] Build, CI or installer

## How was it tested?

<!-- Commands you ran and what you checked. -->

- [ ] `uv run pytest` (fast tests, no GPU) passes
- [ ] `uv run pytest -m slow` (real F5-TTS / XTTS v2 models) passes, if engines or audio changed
- [ ] Tried it in the app or the CLI

## Checklist

- [ ] User-facing CLI and UI messages are in English, with the Spanish translation (`PODCAST_TTS_LANG=es`) updated as well
- [ ] Documentation updated (README.md and README.es.md, docs/) if behaviour changed
- [ ] CHANGELOG.md updated under "Unreleased"
- [ ] No API keys, `.env`, `output/`, `.cache/`, `.venv/` or model weights committed
- [ ] Any new model or service has its license declared (`license_info`) and listed in MODELS_AND_LICENSES.md
- [ ] Dependencies changed only through `pyproject.toml` + `uv lock --python 3.11`, without raising torch above 2.8 or transformers to 5
