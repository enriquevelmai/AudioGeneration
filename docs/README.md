# Documentation

Start with the main [README](../README.md) (also in [Spanish](../README.es.md)). The documents below go
deeper into specific topics.

## For users

| Document | Language | What it covers |
|---|---|---|
| [MODELS_AND_LICENSES.md](../MODELS_AND_LICENSES.md) | English | Every model and cloud service: repository, license, commercial use, download and cache location |
| [COMMERCIAL_USE.md](COMMERCIAL_USE.md) | English | Which engines allow commercial use, setting up ElevenLabs / Azure AI Speech / OpenAI, voice consent, pre-publishing checklist |
| [SKILL.md](SKILL.md) | English | The optional `podcast-tts` skill for Claude Code: how it finds the project, installing and removing it |
| [MCP.md](MCP.md) | English | The MCP server for AI assistants (Claude Desktop, Claude Code, Cursor, VS Code...): installation, tools, timeouts, security |

## For developers

| Document | Language | What it covers |
|---|---|---|
| [CONTRIBUTING.md](../CONTRIBUTING.md) | English | Development setup with uv, tests, style, adding an engine |
| [ENGINES_PLUGINS.md](ENGINES_PLUGINS.md) | English | Writing a third-party TTS engine as a plugin (entry points, `LicenseInfo`, full example) |
| [ENGINES.md](ENGINES.md) | English | Installation layers, version pins and why, verified F5-TTS and XTTS v2 APIs, measured speeds, Windows gotchas |
| [DECISIONS.md](DECISIONS.md) | English | Technical decision log |
| [CHANGELOG.md](../CHANGELOG.md) | English | Release history |

## Other references

- Script format reference with full examples:
  [skill/podcast-tts/references/script-format.md](../skill/podcast-tts/references/script-format.md).
- Example scripts: [examples/](../examples/) (start with `english_episode.md`). `guiones/` is where the app saves your own scripts
  (ignored by git).
