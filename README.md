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

Interfaz web local (Gradio), en castellano:

```powershell
python -m podcast_tts ui                      # http://127.0.0.1:7860
python -m podcast_tts ui --port 7861 --inbrowser
python -m podcast_tts ui --host 0.0.0.0       # accesible desde la red local
python -m podcast_tts ui --share              # enlace público temporal de Gradio
```

Arranca en un par de segundos sin cargar ningún modelo: F5-TTS / XTTS se cargan
en la primera síntesis (la primera generación tarda más). Solo se sintetiza una
cosa a la vez.

Pestañas:

- **Guion → Podcast**: editor precargado con `examples/ejemplo.md`, motor
  (*auto (según voz)*, `f5`, `xtts` o `dummy` para probar tiempos sin modelos),
  nombre del fichero, formato (mp3/wav), bitrate y normalización a -16 LUFS.
  *Validar* muestra la tabla de segmentos (nº, tipo, voz, idioma, texto, línea) y
  las voces usadas, avisando si alguna no existe. *Generar* sintetiza en segundo
  plano con barra de progreso y log; al terminar muestra el reproductor y el
  enlace de descarga. El resultado se guarda en `output/<nombre>.<formato>`.
  Los errores del guion se indican con su número de línea. *Cargar guion* abre
  un `.md`; *Guardar guion* lo guarda en `guiones/<nombre>.md`. Las rutas
  relativas de música/sfx se buscan en `examples/`, el directorio actual y la
  raíz del proyecto. Incluye una tabla de ayuda con las etiquetas.
- **Voces**: tabla de voces (nombre, idioma, motor, descripción, duración del
  clip, speaker XTTS, velocidad), reproductor del `ref.wav` de la voz
  seleccionada, *Probar voz* (sintetiza una frase corta en su idioma o la que
  escribas) y *Eliminar voz* (pide confirmación). En *Añadir voz* subes o grabas
  con el micrófono un clip de 5-15 s con su transcripción exacta, o eliges un
  speaker integrado de XTTS en lugar del clip.
- **Sistema**: estado de CUDA y la GPU, motores disponibles, rutas (voces, caché,
  salida, guiones) con tamaños, botón *Vaciar caché de síntesis* y la lista de
  ficheros de `output/` para descargar.

## Tests

```powershell
python -m pytest tests
```
