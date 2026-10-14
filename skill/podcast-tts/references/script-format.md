# podcast_tts script format (full reference)

Source of truth: `src/podcast_tts/script_parser.py`. When in doubt, run `python -m podcast_tts parse script.md`.

## 1. File

- UTF-8 Markdown (with or without BOM), `.md` extension. Line endings `\n` or `\r\n`.
- Optionally starts with front matter between `---` lines (closed with `---` or `...`).
- The rest is spoken text with `[type:value attributes]` tags interleaved anywhere in a line
  (a line can hold several tags with text between them).

## 2. Front matter

| Key | Aliases | Type | Effect |
|---|---|---|---|
| `title` | `titulo`, `título` | text | Title (metadata) |
| `lang` | `idioma` | code | Default language of the script (`es`, `en`, `fr`...) |
| `default_voice` | `voz`, `voice` | name | Voice for text that appears before any `[voice:]` |
| `engine` | `motor`, `default_engine` | `f5`/`xtts` | Default engine of the script |
| `paragraph_pause` | `pausa_parrafo` | number (s) | Pause between paragraphs (0.4 by default) |

Unknown keys or invalid values are errors.

## 3. Tags

English tags are canonical; the Spanish ones are accepted as aliases:

| Tag | Spanish alias |
|---|---|
| `[voice:]` | `[voz:]` |
| `[pause:]` | `[pausa:]` |
| `[music:]` | `[musica:]`, `[música:]` |
| `[music:... bg]` / `background` | `fondo` |
| `[music:stop]` | `[music:fin]`, `[music:parar]` |
| `[sfx:]` | — |
| `[title:]` | `[titulo:]`, `[título:]` |

Tag names are case-insensitive. Attributes are `key=value` pairs separated by spaces; quote values
that contain spaces.

### `[voice:name ...]`
Switches the speaker from that point until the next `[voice:]`. Every `[voice:]` resets the attributes
(`lang`/`speed` are not inherited from the previous one).
- `lang=xx`: language of this stretch.
- `speed=N`: speed (0.25-4.0; 1.0 is normal; 0.9-1.1 is the sensible range).
- `engine=f5|xtts`: engine for this stretch.
Example: `[voice:carlos lang=en speed=0.95 engine=xtts]`

### `[pause:N]`
Silence of N seconds (an `s` suffix is allowed: `[pause:2s]`). A single value only.

### `[music:path ...]`
- Without a flag: inserts the whole clip at that point and time advances by its duration.
  `vol=0-1` (default 1.0), `fade=s` (default 0).
- With the `bg` / `background` flag (or `fondo`, or `bg=true`): looping background music under the
  following voices, with automatic ducking. `vol` defaults to 0.15, `fade` to 1.5.
- `[music:stop]` (or `fin`, `parar`): stops the background music; `fade` defaults to 1.5.
- `volume=` is a synonym of `vol=`.

### `[sfx:path vol=N]`
Overlaid effect starting at that point; it does NOT advance time. `vol` defaults to 1.0.

### `[title:text]`
Sets the title (metadata); it is not synthesized.

## 4. Processing rules

- A line that starts (after spaces) with `#` is a full comment, even if it contains tags.
- `<!-- ... -->`: HTML comment; it can span several lines or sit in the middle of one, and it is not
  spoken. An unclosed `<!--` is an error.
- Brackets that are not `[type:...]` (checkboxes `- [ ]`, `[laughs]`) are read as text, and links
  `[text](url)` are read as "text". `[word:...]` with an unknown type is an error.
  Comments are useful for structure (`# Section 2`) and for disabling music (`# [music:intro.mp3]`).
- Empty line: ends the paragraph and inserts `paragraph_pause` before the next text.
- Single line breaks inside a paragraph are joined with a space.
- Text is split into sentences (`. ! ? …` and line breaks) and grouped into chunks of up to
  `--max-chars` (250) without splitting sentences; a longer sentence is cut at commas/spaces (avoid it).
- Audio paths are relative to the script file (or absolute). Formats: anything ffmpeg can read.
- Errors (unknown tag, invalid attribute, number out of range, malformed front matter, text with no
  voice) are reported with the line number; the command exits with code 1.

### Priorities
- Language: `[voice: lang=]` > front matter `lang` > `voice.json` `lang`.
- Engine: CLI `--engine` > `[voice: engine=]` > front matter `engine` > `voice.json` `engine`.
- Speed: `[voice: speed=]` > `voice.json` `speed`.

## 5. Examples

The voice names (`emma`, `david`, `ana`, `carlos`, `narrator`) are illustrative: replace them with real
voices from `python -m podcast_tts voices list --json`.

### 5.1 Short monologue

```markdown
---
title: Tip of the Day
lang: en
default_voice: emma
---

Hi, I'm Emma, and this is the tip of the day.

Today we're talking about something simple: drinking water. Experts recommend between one and a half
and two liters a day. There's no need to obsess over it; just keep a bottle within reach.

[pause:0.8]
That's all for today. See you tomorrow!
```

### 5.2 Bilingual dialogue with background music (Spanish content, English tags)

The tags are always the same; only the spoken text and `lang` change. This episode is in Spanish,
with a few lines in English:

```markdown
---
title: Puente de idiomas - Episodio 1
lang: es
engine: f5
---

# Intro: full theme, then soft background music (paths relative to this script)
[music:assets/intro.mp3 vol=0.7 fade=1]
[music:assets/fondo.mp3 bg vol=0.12 fade=2]

[voice:ana]
¡Bienvenidos a Puente de idiomas! Hoy me acompaña Carlos, que vive en Londres desde hace diez años.

[voice:carlos]
Hola, Ana. Gracias por invitarme. Hoy vamos a practicar algunas frases útiles para viajar.

[voice:carlos lang=en]
Excuse me, could you tell me where the train station is?

[voice:ana]
Perfecto. Eso significa: perdone, ¿podría decirme dónde está la estación de tren?

[voice:ana lang=en speed=0.9]
Thank you very much. Have a nice day!

[pause:1]
[voice:carlos]
Y hasta aquí el episodio de hoy. ¡Nos escuchamos la semana que viene!

[music:stop fade=3]
[pause:1.5]
```

### 5.3 News with several sections

```markdown
---
title: Monday News Roundup
lang: en
default_voice: narrator
paragraph_pause: 0.5
---

[music:assets/header.mp3 vol=0.8 fade=0.5]

Good morning. It's eight a.m. on Monday, October twelfth, and this is the news roundup.

[pause:1.2]
# ---------- Section 1: Technology ----------
[sfx:assets/transition.wav vol=0.6]
[voice:emma]
We start with technology. A new generation of voice models makes it possible to create complete
podcasts on a home computer, without relying on cloud services.

According to their developers, the quality is already comparable to a professional voice-over.

[pause:1.2]
# ---------- Section 2: Economy ----------
[sfx:assets/transition.wav vol=0.6]
[voice:david]
In economic news, inflation eased to two point one percent in September,
three tenths of a point lower than in August.

[pause:1.2]
# ---------- Section 3: Weather ----------
[sfx:assets/transition.wav vol=0.6]
[voice:narrator speed=1.05]
And the weather: clear skies across most of the country, with highs of seventy-five degrees in the south.

[pause:1]
That's all for today. Thanks for listening, and have a great week.
[music:assets/outro.mp3 vol=0.7 fade=2]
```
