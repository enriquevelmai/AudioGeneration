# podcast_tts

Generador local de podcasts: escribes un guion en Markdown con etiquetas
(`[voz:ana]`, `[pausa:1.5]`, `[musica:intro.mp3]`...) y obtienes un MP3 con
voces clonadas a partir de clips cortos, todo en tu ordenador (GPU NVIDIA).

- Motores TTS: **F5-TTS** (por defecto) y **XTTS v2** (Coqui), seleccionables por voz.
- Música de fondo con *ducking*, efectos, pausas y normalización a ~-16 LUFS.
- Caché de síntesis: al regenerar solo se sintetizan las frases que han cambiado.
- CLI en castellano y UI web local (Gradio).

## Instalación

TODO

## Estructura

```
AudioGeneration/
├── src/podcast_tts/
│   ├── script_parser.py   # parser del guion -> Segments (+ JSON)
│   ├── voices.py          # registro de voces en voices/
│   ├── assembler.py       # síntesis + mezcla + normalización + exportación
│   ├── cli.py             # python -m podcast_tts ...
│   └── engines/
│       ├── base.py        # protocolo TTSEngine
│       ├── f5.py          # F5-TTS
│       ├── xtts.py        # XTTS v2
│       └── dummy.py       # motor de pruebas (tonos)
├── voices/<nombre>/       # ref.wav + ref.txt + voice.json
├── examples/ejemplo.md    # guion de ejemplo
├── tests/                 # pytest
├── output/                # audios generados (ignorado por git)
└── .cache/tts/            # caché de síntesis (ignorada por git)
```

## Formato del guion

Un guion es un fichero `.md` en UTF-8. Opcionalmente empieza con un *front matter*:

```markdown
---
title: Mi episodio
lang: es              # idioma por defecto del guion
default_voice: ana    # voz para el texto sin etiqueta [voz:...]
engine: f5            # motor por defecto (f5 | xtts)
paragraph_pause: 0.4  # pausa entre párrafos (s)
---
```

### Etiquetas

| Etiqueta | Alias | Efecto | Atributos |
|---|---|---|---|
| `[voz:nombre]` | `[voice:nombre]` | Cambia de hablante hasta la siguiente etiqueta de voz | `lang=es\|en\|...`, `speed=1.1`, `engine=f5\|xtts` |
| `[pausa:1.5]` | `[pause:1.5]` | Silencio de N segundos | — |
| `[musica:ruta.mp3]` | `[music:...]`, `[música:...]` | Inserta un clip musical (avanza el tiempo) | `vol=0-1` (1.0), `fade=seg` (0) |
| `[musica:ruta.mp3 fondo]` | `bg`, `background`, `bg=true` | Música de fondo bajo las voces siguientes, en bucle, con *ducking* | `vol=0-1` (0.15, volumen bajo la voz), `fade=seg` (1.5) |
| `[musica:stop]` | `fin`, `parar` | Detiene la música de fondo con fundido | `fade=seg` (1.5) |
| `[sfx:ruta.wav]` | — | Efecto puntual superpuesto desde ese punto (no avanza el tiempo) | `vol=0-1` (1.0) |
| `[titulo:...]` | `[title:...]`, `[título:...]` | Metadato (no se sintetiza) | — |

Reglas:

- Las líneas que empiezan por `#` (encabezados) o `<!--` son comentarios: no
  suenan, aunque contengan etiquetas (útil para "comentar" música).
- Una línea vacía separa párrafos e inserta una pausa corta (0.4 s por defecto).
- El texto se trocea en frases (`. ! ? …` y saltos de línea) y se agrupa en
  trozos de máximo ~250 caracteres sin cortar frases (`--max-chars`).
- Las rutas de música/sfx son relativas al guion (o absolutas). Las rutas con
  espacios van entre comillas: `[musica:"mis audios/intro.mp3"]`.
- Una etiqueta desconocida o un valor inválido da un error con el número de línea.
- Prioridad: idioma = etiqueta > front matter > `voice.json`; motor =
  `--engine` > etiqueta > front matter > `voice.json`; velocidad = etiqueta > `voice.json`.

Ejemplo:

```markdown
[voz:ana] Hola y bienvenidos. [pausa:1]
[musica:assets/fondo.mp3 fondo vol=0.12]
[voz:carlos lang=en speed=0.95] Hi everyone!
[musica:stop fade=3]
```

Ver [`examples/ejemplo.md`](examples/ejemplo.md).

## Voces

Cada voz vive en `voices/<nombre>/`:

- `ref.wav`: clip de referencia de 5-15 s (se convierte a mono 24 kHz 16 bit).
- `ref.txt`: transcripción exacta del clip (imprescindible para F5-TTS).
- `voice.json`: `{name, lang, engine, description, xtts_speaker, speed}`.

## Uso (CLI)

```powershell
# Generar un episodio
python -m podcast_tts generate examples/ejemplo.md -o output/episodio.mp3

# Probar tiempos y mezcla sin modelos (tonos en vez de voces)
python -m podcast_tts generate examples/ejemplo.md -o output/prueba.mp3 --engine dummy

# Ver cómo se interpreta un guion (JSON)
python -m podcast_tts parse examples/ejemplo.md

# Gestionar voces
python -m podcast_tts voices list
python -m podcast_tts voices add ana grabacion.wav --text "Transcripción exacta del clip." --lang es --engine f5
python -m podcast_tts voices add narrador --engine xtts --xtts-speaker "Claribel Dervla" --lang en
python -m podcast_tts voices remove ana
```

Opciones útiles de `generate`: `--voices-dir`, `--max-chars`, `--bitrate 192k`,
`--lufs -16`, `--no-normalize`, `--no-cache`, `--cache-dir`, `-q`.

## UI

TODO

## Tests

```powershell
python -m pytest tests
```
