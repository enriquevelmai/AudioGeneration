# MCP server reference

`podcast-tts mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io) server over
**stdio**, so any MCP client (Claude Desktop, Claude Code, Cursor, VS Code, Windsurf...) can turn
"make me a podcast about X" into a finished MP3: the assistant writes the script, validates it and
generates the audio locally with your voices.

- Code: [`src/podcast_tts/mcp_server.py`](../src/podcast_tts/mcp_server.py) (official Python SDK,
  `FastMCP`).
- Requires the `mcp` extra (`uv sync --extra mcp ...`); `bats\install_integrations.bat` installs it
  and registers the server.
- Start: `podcast-tts mcp`, `python -m podcast_tts mcp` or `podcast-tts-mcp`
  (options: `--output-dir DIR`, `--voices-dir DIR`).

## Install

```bat
bats\install_integrations.bat                 :: detects Claude Code / Claude Desktop and asks
bats\install_integrations.bat /y              :: everything detected, no questions
bats\install_integrations.bat /claude-code    :: skill + claude mcp add --scope user podcast-tts
bats\install_integrations.bat /claude-desktop :: merges into %APPDATA%\Claude\claude_desktop_config.json
bats\install_integrations.bat /print          :: prints the JSON for other clients
bats\install_integrations.bat --uninstall     :: removes the registration (keeps the skill)
```

It is idempotent. For Claude Desktop it only adds or updates the `podcast-tts` entry in
`mcpServers`, keeps every other entry and writes `claude_desktop_config.json.bak` before saving
(it refuses to touch a file that is not valid JSON). It also handles the Microsoft Store build
(`%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`). Restart Claude Desktop afterwards
(quit it from the system tray too).

Testing options that change nothing real: `--dry-run` (prints the `uv` / `claude` commands and
the result of the JSON merge without writing) and `--config-path FILE` (merge into another file).
Run `scripts\install_integrations.py --help` for all options.

### Manual configuration

Claude Desktop, Cursor (`~/.cursor/mcp.json`), Windsurf and most clients:

```json
{
  "mcpServers": {
    "podcast-tts": {
      "command": "C:\\path\\to\\AudioGeneration\\.venv\\Scripts\\python.exe",
      "args": ["-m", "podcast_tts", "mcp"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\AudioGeneration\\src",
        "PYTHONUTF8": "1",
        "COQUI_TOS_AGREED": "1"
      }
    }
  }
}
```

VS Code (`.vscode/mcp.json`, or *MCP: Open User Configuration*) uses `"servers"` and
`"type": "stdio"` with the same `command`, `args` and `env`. Claude Code:

```bat
claude mcp add --scope user podcast-tts -e PYTHONPATH=C:\path\to\AudioGeneration\src -e PYTHONUTF8=1 -e COQUI_TOS_AGREED=1 -- C:\path\to\AudioGeneration\.venv\Scripts\python.exe -m podcast_tts mcp
```

`bats\install_integrations.bat /print` prints these blocks with the real paths of your install.
`PYTHONPATH` makes the server work even when the project folder has accents or `ñ`.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `PODCAST_TTS_OUTPUT_DIR` | `<project>\output` | Where audio files are written |
| `PODCAST_TTS_SCRIPTS_DIR` | `<project>\guiones` | Where `generate_podcast` saves the script (`save_script`) |
| `PODCAST_TTS_VOICES_DIR` | `<project>\voices` | Voice folder |
| `PODCAST_TTS_MCP_WAIT` | `45` | Default seconds a generation tool waits before returning a `job_id` |
| `PODCAST_TTS_DEVICE` | auto | `cuda` or `cpu` |

## Tools

All descriptions are in English; scripts and text can be in any language. Results are JSON.

| Tool | Signature | Returns |
|---|---|---|
| `list_voices` | `()` | `voices[]`: `name`, `lang`, `engine`, `description`, `cloud`, `has_reference_clip`, `xtts_speaker` |
| `list_engines` | `(check_gpu: bool = false)` | `engines[]`: `kind`, `license`, `commercial_use`, `available`, `configured`, `ready`, `missing_config` (+ `gpu`, `device`) |
| `get_script_format` | `()` | Markdown guide: format, podcast structure, TTS writing tips, full tag reference |
| `validate_script` | `(script: str, engine: str \| None = None)` | `valid`, `errors[]` (`line`, `message`), `warnings`, `voices_used`, `missing_voices`, `estimated_duration`, `word_count`, `engines`, `license_notice`, `segments` |
| `generate_podcast` | `(script: str, output_name: str, engine: str \| None = None, format: "mp3" \| "wav" = "mp3", overwrite: bool = false, save_script: bool = true, wait_seconds: float \| None = None)` | `status` `done` with `output_path` (absolute), `duration`, `duration_seconds`, `generation_seconds`, `size_bytes`, `license_notice`, `script_path`; or `running` with `job_id` |
| `generate_podcast_from_file` | `(path: str, output_name: str \| None = None, engine, format, overwrite, wait_seconds)` | Same as `generate_podcast` |
| `get_generation_status` | `(job_id: str, wait_seconds: float \| None = None)` | `running` / `done` / `error` |
| `synthesize_text` | `(text: str, voice: str, lang: str \| None = None, output_name: str \| None = None, engine: str \| None = None, speed: float \| None = None, format = "mp3", overwrite = false, wait_seconds = None)` | Same as `generate_podcast` (file `tts_<voice>.mp3` by default) |
| `add_voice` | `(name: str, audio_path: str, transcript: str, lang: str = "es", engine: str = "f5", description: str = "", overwrite: bool = false)` | The saved voice and any warnings (clip too short or trimmed) |
| `list_outputs` | `(limit: int = 30)` | `output_dir` and `files[]` (`name`, `path`, `size_bytes`, `modified`), newest first |
| `open_output_folder` | `()` | Opens the output folder in the file explorer of the computer running the server |

Also available:

- **Prompt `podcast`** (`topic`, `voices`, `minutes`, `language`): "Create a podcast about
  {topic} with {voices} lasting ~{minutes} min". It walks the assistant through the whole flow:
  list voices, read the format, research the topic (if it has web tools), write the script,
  validate, generate and report the path.
- **Resource `podcast-tts://script-format`**: the same guide as `get_script_format`.

## Long generations and client timeouts

The first generation loads the models (10-30 s); after that F5-TTS runs at about 0.3-0.5x real
time on an RTX 4080 SUPER (a 1-minute dialogue took 29 s including the model load; a 5-minute
episode takes about 1.5-2.5 min). Many clients cancel a tool call after about 60 s, so the server
never blocks for that long:

1. `generate_podcast` waits up to `wait_seconds` (default 45 s, `PODCAST_TTS_MCP_WAIT`) and
   sends a progress notification per segment (`notifications/progress`: "Sintetizando [ana] ...",
   pauses, mixing, export; strictly increasing, total = segments + 1).
2. If the audio is not finished, it returns `{"status": "running", "job_id": ...}` and the work
   continues in the background (one generation at a time: there is one GPU).
3. The assistant calls `get_generation_status(job_id)`, which waits again and returns
   `{"status": "done", "output_path": ..., "duration": ...}`.

If your client allows longer calls you can raise the wait: pass `wait_seconds` (max 600) or set
`PODCAST_TTS_MCP_WAIT` in the server's `env`. In Claude Code, the per-call limit is the
`MCP_TOOL_TIMEOUT` environment variable (milliseconds) and the startup limit is `MCP_TIMEOUT`.
Jobs live in the server process: if the client restarts the server, an unfinished job is lost.

## Security and paths

- Output files always go to the output folder. `output_name` must be a plain name (letters,
  numbers, spaces, `_`, `-`, `.`); folders, drive letters and `..` are rejected. Existing files get
  a `-2`, `-3`... suffix unless `overwrite` is true.
- Music and sfx paths inside scripts follow the same rules as the web UI in remote mode
  (`allow_external_paths=False`): only audio files, relative to `examples/` (scripts passed as
  text) or to the script's folder (`generate_podcast_from_file`), or to the project folder; no
  absolute paths and no `..`. Violations are reported by `validate_script` with the line number.
- `add_voice` only reads the local audio file you name and writes into the voices folder.
  Only clone voices of people who have given their consent.
- **stdout carries only the protocol.** At startup the server keeps a private copy of the real
  stdout for JSON-RPC, points file descriptor 1 at stderr (so `print` from torch, f5-tts, gradio
  or ffmpeg ends up in stderr / the client's log) and replaces stdin with `NUL` so no library can
  swallow protocol messages with `input()`. Logs go to stderr.

## Example conversation

> **You:** Make me a 3-minute podcast about the history of coffee.
>
> **Assistant:** *(calls `list_voices`, `get_script_format`, writes a ~450-word dialogue between
> ana and carlos, calls `validate_script` -> valid, estimated 3:05, then `generate_podcast` with
> `output_name: "history_of_coffee"`)*
>
> Done: `C:\...\AudioGeneration\output\history_of_coffee.mp3` (3:02, generated in 1 min 20 s).
> Note: F5-TTS is for non-commercial use only. Do you want me to change the tone, the length or the voices?

## Tests

- `pytest tests/test_mcp_server.py` starts `python -m podcast_tts mcp` as a subprocess and talks
  to it with the SDK client (`ClientSession` + `stdio_client`): tools, prompt, validation with line
  numbers, `dummy` generation with progress, job polling, path checks and a raw JSON-RPC session
  that asserts every stdout line is valid JSON.
- `pytest -m slow tests/test_mcp_server.py` does the same with the real F5-TTS model.
- `pytest tests/test_install_integrations.py` checks the JSON merge, backups, idempotency and the
  `claude mcp` commands with fake files and a fake `claude`.
