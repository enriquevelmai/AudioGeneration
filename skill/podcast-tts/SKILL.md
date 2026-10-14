---
name: podcast-tts
description: >-
  Generate podcasts and spoken audio locally with the podcast_tts project (F5-TTS and XTTS v2 running
  locally on an NVIDIA GPU or the CPU, plus optional ElevenLabs, Azure AI Speech and OpenAI engines). Use whenever the user asks to create a podcast or episode, turn a script or any
  text into audio/MP3, record a voice-over or narration, read text aloud, do text-to-speech (TTS) in
  English, Spanish/castellano or other languages, make a dialogue between several voices, add background
  music to speech, or clone/add a voice from an audio clip. Also triggers on Spanish requests like "hazme un podcast sobre X",
  "genera un podcast", "pasa este guion a audio", "voz en off", "locucion", "narracion", "clonar voz".
  Prefer it over ad-hoc TTS tools such as edge-tts or system voices.
---

# podcast-tts: local podcasts and TTS

Always use this project to generate speech; do not fall back to `edge-tts`, SAPI or other standalone TTS tools.
If the user needs commercial use, pick an engine with a commercial license (`elevenlabs`, `azure`, `openai`): the local models are non-commercial (see `podcast-tts engines`).

## Language

- Reply to the user in the user's language.
- Write the podcast script in the language the user asks for; if they do not say, use the user's
  language. Choose voices whose `lang` matches (or set `lang=` per stretch) and set the front matter
  `lang` accordingly.
- Script tags are always the English ones (`[voice:]`, `[pause:]`, `[music:]`...), whatever language
  the spoken text is in. The Spanish tags (`[voz:]`, `[pausa:]`, `[musica:]`...) are still accepted as aliases.

## How to call the CLI

ALWAYS use one of this skill's two wrappers; do not type user paths by hand. They find the project
(`PODCAST_TTS_HOME` variable; otherwise the target of the `~/.claude/skills/podcast-tts` junction;
otherwise the relative path inside the repository), set `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`
and `COQUI_TOS_AGREED=1` (without the latter XTTS hangs waiting for input) and forward all arguments
to the CLI.

Bash (Git Bash):
```bash
T=~/.claude/skills/podcast-tts/scripts/generate.sh
bash "$T" voices list --json
bash "$T" generate "$PWD/script.md" -o "$PWD/episode.mp3"
bash "$T" --where     # prints the project root (contains guiones/, output/, voices/)
```

PowerShell:
```powershell
$T = "$HOME\.claude\skills\podcast-tts\scripts\generate.ps1"
& $T voices list --json
& $T generate C:\path\script.md -o C:\path\episode.mp3
& $T --where
```

In the examples below, `<cli>` is either wrapper. (`generar.sh`/`generar.ps1` still exist as
compatibility aliases.) If it says it cannot find the project or the environment, the user must run
`bats\install.bat` in the repository root (or set `PODCAST_TTS_HOME`).

Voices are looked up in `<project>/voices` (`--voices-dir` for another folder). The wrapper does not
change directory: use absolute paths for the script and the output.

Subcommands:
- `generate SCRIPT.md -o OUTPUT.mp3` — options: `--engine f5|xtts|dummy` (forces the engine for everything),
  `--max-chars 250`, `--bitrate 192k`, `--sample-rate 44100`, `--lufs -16`, `--no-normalize`,
  `--no-cache`, `--cache-dir`, `-q`. Output `.mp3` or `.wav`. Without `-o` it writes `output/<script>.mp3` in the cwd.
- `parse SCRIPT.md [--compact]` — validates and prints the segments as JSON (no synthesis).
- `voices list [--json]`, `voices add ...`, `voices remove NAME`.
- `ui` — local web interface (Gradio).
- `models list|status [--json]` — models (repo, size, license, commercial use) and whether they are
  downloaded. `models download [name|all]` fetches them now; `models update` checks for new versions.

## MCP tools or CLI

If the session has the MCP tools of the `podcast-tts` server (`list_voices`,
`get_script_format`, `validate_script`, `generate_podcast`, `get_generation_status`,
`synthesize_text`...), **use them instead of the CLI**: they return JSON, validate with line numbers
and report progress. If `generate_podcast` returns `status: "running"`, call
`get_generation_status(job_id)` until `done`; do not restart the generation. Otherwise use the CLI
through the wrappers above. To install the MCP server: `bats\install_integrations.bat` (see `docs/MCP.md`).

## "Make me a podcast about X": end-to-end flow

1. **Clarify only what is essential.** If the user does not say, assume: 2 voices (`emma` and `david`
   in English; `ana` and `carlos` in Spanish), about 3-5 minutes, and the user's language. Ask
   only if something cannot be assumed (e.g. an ambiguous topic or commercial use).
2. **Voices**: `list_voices` (MCP) or `voices list --json`. NEVER invent voice names: use only the
   ones listed (check `name`, `lang`, `engine`, `description`). If none fits, ask or create one
   (see "Adding a voice").
3. **Research** the topic if you have web tools (search, fetch): concrete facts, dates and verified
   anecdotes. Otherwise use your own knowledge and avoid dubious claims.
4. **Write the script** with a podcast structure:
   - **intro with a hook** (15-30 s): a question or surprising fact, and an introduction of the topic;
   - **2-4 blocks**, each with one clear idea, marked with `# Block N: ...` comments and
     separated with `[pause:1]`; spoken **transitions** ("And that brings us to...");
   - **closing**: short recap, one idea to remember, and a sign-off;
   - **natural dialogue**: alternating turns of 1-4 sentences, reactions ("No way!",
     "Exactly"), questions between hosts; no long monologues or lists;
   - **length**: ~150 words per minute (3 min ≈ 450 words, 5 min ≈ 750).
   Follow the format and writing tips below (or `get_script_format` over MCP).
5. **Save** the script to `<project>/guiones/<topic>.md` (`--where` gives the root; create the folder
   if it does not exist; the MCP `generate_podcast` saves it itself with `save_script`).
6. **Validate**: `validate_script` (MCP) or `parse script.md`. Fix each error (it gives the line number)
   and repeat until it is valid. `"lang": null` in a segment means "no `lang=` tag": the
   front matter `lang` is used if present, otherwise the one in `voice.json`.
7. **Generate**: `generate_podcast` (MCP) or `generate script.md -o <project>/output/<topic>.mp3`.
   To test timing and mixing without a GPU: the `dummy` engine (tones instead of speech).
8. **Report** the absolute path of the file, its duration and the generation time (the MCP returns
   them; the CLI prints them at the end, or `ffprobe -v error -show_entries format=duration -of
   csv=p=0 output.mp3`), plus the license notice if there is one.
9. **Offer changes**: tone, length, voices, sections, music. When regenerating after editing the script,
   the cache (`.cache/tts`) only re-synthesizes the sentences that changed.

## Script format (summary)

Optional front matter at the top of the file:
```markdown
---
title: My episode
lang: en              # default language (alias: idioma)
default_voice: emma   # voice for text with no preceding [voice:] (aliases: voz, voice)
engine: f5            # f5 | xtts (aliases: motor, default_engine)
paragraph_pause: 0.4  # pause between paragraphs in s (alias: pausa_parrafo)
---
```

| Tag | Spanish alias | Effect | Attributes / example |
|---|---|---|---|
| `[voice:name]` | `[voz:]` | Switches speaker until the next `[voice:]` | `lang=en`, `speed=0.25-4`, `engine=f5\|xtts` → `[voice:david lang=es speed=1.05]` |
| `[pause:1.5]` | `[pausa:]` | Silence of N s (`1.5` or `1.5s`) | `[pause:0.8]` |
| `[music:path]` | `[musica:]`, `[música:]` | Music clip that advances time | `vol=0-1` (1.0), `fade=s` (0) → `[music:intro.mp3 vol=0.6 fade=1]` |
| `[music:path bg]` | flag `fondo` (also `background`, or `bg=true`) | Looping background music under the voices, with ducking | `vol` (0.15), `fade` (1.5) → `[music:bed.mp3 bg vol=0.12]` |
| `[music:stop]` | `fin`, `parar` | Stops the background music with a fade | `fade` (1.5) → `[music:stop fade=3]` |
| `[sfx:path]` | — | Overlaid effect; does not advance time | `vol` (1.0) → `[sfx:ding.wav vol=0.7]` |
| `[title:text]` | `[titulo:]`, `[título:]` | Metadata; not spoken | `[title:Episode 3]` |

Key rules:
- Lines starting with `#` and `<!-- ... -->` blocks (including multi-line ones) are comments
  (not spoken even if they contain tags).
- Blank line = new paragraph + short pause (0.4 s).
- Music/sfx paths are relative to the script or absolute; quote them if they contain spaces: `[music:"my audio/a.mp3"]`.
- Unknown tag or attribute → error with the line number.
- Priorities: **language** = tag > front matter > `voice.json`; **engine** = `--engine` > tag >
  front matter > `voice.json`; **speed** = tag > `voice.json`.
- Text before any `[voice:]` and no `default_voice` → error.
- **Bilingual scripts**: do NOT put `lang` in the front matter (it would force that language on every
  voice, e.g. `emma` would read English with the Spanish model). Let each voice use the `lang` from its
  `voice.json`, or set it per stretch: `[voice:ana lang=en]`.

Full reference and 3 example scripts: `references/script-format.md` (read it if the script uses music,
several languages or several sections).

## Writing tips for TTS

- Short, complete sentences, each under 250 characters (text is split at `. ! ? …`).
- Write numbers, dates, times and amounts as words: "twenty twenty-six", "half past nine", "fifteen percent"
  (in Spanish: "dos mil veintiséis", "las nueve y media").
- Expand abbreviations and acronyms: "for example" (not "e.g."), "Doctor" (not "Dr."); spell URLs out in words.
- Punctuation sets the rhythm: commas = breath, period = pause; use `¿?` and `¡!` in Spanish.
- No emojis, Markdown (`**`, bullets, links), tables or code in the spoken text.
  `#` headings work as structure comments.
- Separate sections with `[pause:1]`–`[pause:1.5]`; alternate voices for a livelier pace.
- Another language: `[voice:x lang=en]` instead of mixing languages within a sentence.

## F5 vs XTTS

- **f5 (default)**: best voice-cloning quality in English and Spanish. Needs `ref.wav` + `ref.txt`
  with the exact transcription of the clip.
- **xtts**: for the other 15 languages (fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, hu, ko, ja, hi) or
  to use one of the 58 built-in speakers without a clip (e.g. "Ana Florence", "Claribel Dervla",
  "Alma María", "Luis Moray"). Stochastic (duration varies); limit of ~239 characters per sentence in `es`.

## Adding a voice

```bash
# Cloned: a 5-15 s clip, clean, no music, plus its EXACT transcription
<cli> voices add lucy "C:/path/clip.wav" --text "Exact transcription of the clip." --lang en --engine f5 --description "female, warm"
#   (--text-file trans.txt instead of --text; --speed 1.05; --overwrite to replace)
# XTTS built-in speaker (no clip):
<cli> voices add narrator --engine xtts --xtts-speaker "Claribel Dervla" --lang en
```
It ends up in `voices/<name>/` (`ref.wav` mono 24 kHz, `ref.txt`, `voice.json`). Name: letters, digits, `_` or `-`.
Confirm afterwards with `voices list`.

## Expected timings

- First run: if the models are not downloaded they are fetched automatically (~1.3-1.9 GB each); check
  first with `models status` and, if any are missing, tell the user or run `models download`.
- First model load: 10-30 s (XTTS ~10 s when cached; F5 a few seconds).
- With an NVIDIA GPU (e.g. RTX 4080) ~0.2-0.3× real time: a 10-minute episode takes ~2-3 min.
  On the CPU it is much slower (warn the user and start with short texts). For long scripts use a
  generous timeout (e.g. 600000 ms) or run it in the background.

## Common errors

- **Voice not found**: run `voices list --json` and use a real name, or create the voice.
- **Script error with a line number**: fix the tag/attribute on that line and run `parse` again.
- **Text with no voice**: add `default_voice` to the front matter or a `[voice:]` before the text.
- **ffmpeg / audio cannot be read**: ffmpeg must be on PATH (`ffmpeg -version`); check the
  music/sfx path (relative to the script, not to the cwd).
- **CUDA not available / out of memory**: diagnose with `.venv\Scripts\python.exe scripts\check_env.py`
  in the project root (`--where`; it should print `ALL OK`); close other processes using the GPU
  (e.g. an open UI) and retry. If there is an NVIDIA GPU but the CPU variant was installed: `bats\install_gpu.bat`.
  `PODCAST_TTS_DEVICE=cpu|cuda` forces the device. `--engine dummy` to test without models.
- **The engine cannot be loaded / f5_tts or TTS missing**: the `local` extra is not installed;
  run `bats\install.bat`.
- **XTTS hangs while loading**: `COQUI_TOS_AGREED=1` is missing (the wrappers already set it).
- **UnicodeEncodeError**: `PYTHONUTF8=1` is missing (the wrappers already set it).
- Broken or outdated environment: `bats\install.bat` or `bats\update.bat` in the project root.

## UI

`<cli> ui` launches the local web interface (Gradio). Run it in the background and give the user
the URL it prints (usually http://127.0.0.1:7860). Tabs: "Script → Podcast", "Voices", "System" and
"Settings" (the UI language can be switched to Spanish under Settings -> Language, or with
`PODCAST_TTS_LANG=es`).
