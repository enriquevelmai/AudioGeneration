# podcast_tts

Generador local de podcasts: escribes un guion en Markdown con etiquetas
(`[voz:ana]`, `[pausa:1.5]`, `[musica:intro.mp3]`...) y obtienes un MP3 con
voces clonadas a partir de clips cortos, todo en tu ordenador (GPU NVIDIA o CPU).

- Motores TTS: **F5-TTS** (por defecto) y **XTTS v2** (Coqui), seleccionables por voz.
- Música de fondo con *ducking*, efectos, pausas y normalización a ~-16 LUFS.
- Caché de síntesis: al regenerar solo se sintetizan las frases que han cambiado.
- CLI en castellano y UI web local (Gradio).

## Inicio rápido

En Windows 10/11, desde la carpeta del repositorio (doble clic o en `cmd`):

```bat
bats\install.bat        :: instala uv, Python 3.11 y las dependencias en .venv (detecta GPU NVIDIA)
bats\run.bat            :: abre la UI en el navegador (http://127.0.0.1:7860)
bats\update.bat         :: git pull + dependencias + modelos al día
```

Por línea de comandos (fija antes `set PYTHONUTF8=1` y `set COQUI_TOS_AGREED=1`, o
`$env:PYTHONUTF8='1'; $env:COQUI_TOS_AGREED='1'` en PowerShell):

```powershell
.venv\Scripts\python.exe scripts\check_env.py        # debe terminar en "TODO OK"
.venv\Scripts\podcast-tts.exe generate examples\ejemplo.md -o output\episodio.mp3
.venv\Scripts\podcast-tts.exe models status          # modelos descargados (o python -m podcast_tts ...)
# Desde Claude Code: pide "genera un podcast..." y se activa la skill podcast-tts (docs/SKILL.md)
```

## Instalación

Requisitos:

- Windows 10/11 x64. GPU NVIDIA recomendada (driver reciente; probado en RTX 4080 SUPER 16 GB,
  ~5 GB de VRAM con los tres modelos cargados). Sin GPU funciona en CPU, pero muy lento.
- Nada más: `bats\install.bat` instala [uv](https://docs.astral.sh/uv/) (sin admin) y Python 3.11
  gestionado por uv, en un entorno aislado `.venv` dentro del repositorio.
- `ffmpeg` en el `PATH` para leer/escribir MP3. Si falta, el instalador ofrece instalarlo con
  `winget` (`Gyan.FFmpeg`).
- ~5 GB de disco para los modelos (fuera del repositorio) y ~6 GB para `.venv` con CUDA.

### `bats\install.bat`

1. Instala uv si no está (instalador oficial de astral, en `%USERPROFILE%\.local\bin`).
2. `uv python install 3.11`.
3. Detecta GPU NVIDIA con `nvidia-smi`: si la hay usa PyTorch CUDA 12.6; si no, PyTorch CPU.
4. `uv sync --locked --extra local --extra cuda|cpu --extra dev` (exactamente lo de `uv.lock`) y
   guarda los extras elegidos en `.venv\podcast-tts-extras.txt` (los reutiliza `update.bat`).
5. Comprueba ffmpeg y el entorno (`scripts\check_env.py`).
6. Ofrece descargar ya los modelos (`podcast-tts models download`).
7. Si existe `%USERPROFILE%\.claude`, ofrece instalar la skill de Claude Code.

Opciones: `/y` (o `PODCAST_TTS_NONINTERACTIVE=1`) responde que sí a todo y no hace `pause`;
`/cpu` o `/cuda` (o `PODCAST_TTS_VARIANT`) fuerzan la variante de PyTorch;
`PODCAST_TTS_DOWNLOAD_MODELS=0|1` y `PODCAST_TTS_INSTALL_SKILL=0|1` fijan esas respuestas.
Códigos de salida: 0 bien, 1 error, 2 instalado pero `check_env.py` encontró problemas.

Otros scripts de `bats\`:

- `run.bat`: abre la UI (los argumentos extra van a `podcast_tts ui`, p.ej. `--port 7861`).
- `update.bat`: `git pull --ff-only` (si es un clon con remoto), `uv sync` con los mismos extras
  y `podcast-tts models update` (solo los modelos ya descargados).
- `install_gpu.bat`: pasa de PyTorch CPU a CUDA sin reinstalar el resto (instalaste sin GPU, o
  con el driver roto, y ahora la tienes).

`scripts\setup.ps1` se mantiene por compatibilidad y solo llama a `bats\install.bat /y`
(`-Smoke` descarga modelos y genera audios de prueba; `-Recreate` borra `.venv` antes).

### Dependencias por capas (extras de uv)

| Capa | Qué incluye | Para qué |
|---|---|---|
| núcleo | numpy, pydub, gradio, pyyaml, scipy, pyloudnorm, huggingface-hub | parser, motor `dummy`, CLI, UI, `models`, tests rápidos. Sin torch |
| `local` | f5-tts, coqui-tts, transformers<5, torch/torchaudio 2.8, soundfile | motores F5-TTS y XTTS v2 |
| `cuda` / `cpu` | torch/torchaudio 2.8 desde `download.pytorch.org/whl/cu126` o `/cpu` | variante de PyTorch (excluyentes) |
| `dev` | pytest | tests |

Equivalente manual con uv:

```powershell
uv sync --extra local --extra cuda --extra dev   # GPU NVIDIA
uv sync --extra local --extra cpu --extra dev    # sin GPU
uv sync --extra dev                              # solo núcleo (motor dummy, UI, tests rápidos)
```

### Modelos

No están en el repositorio: se descargan solos la primera vez que se usan, o antes con
`podcast-tts models download [nombre|all]`. `models list` muestra repo, tamaño y licencia;
`models status` si están descargados, dónde y cuánto ocupan; `models update` baja la última revisión.

| Modelo (`models`) | Repo Hugging Face | Uso | Caché | Tamaño | Licencia |
|---|---|---|---|---|---|
| `f5-base` | `SWivid/F5-TTS` (`F5TTS_v1_Base`) | F5, inglés | caché de HF (`HF_HOME`) | ~1.3 GB | CC-BY-NC-4.0 |
| `f5-spanish` | `jpgallegoar/F5-Spanish` | F5, castellano | caché de HF | ~1.3 GB | CC-BY-NC-4.0 |
| `vocos` | `charactr/vocos-mel-24khz` | vocoder de F5 | caché de HF | ~54 MB | MIT |
| `xtts` | `coqui/XTTS-v2` | XTTS, 17 idiomas | `%LOCALAPPDATA%\tts` (`TTS_HOME`) | ~1.9 GB | CPML |
| `whisper` (opcional) | `openai/whisper-large-v3-turbo` | solo si una voz F5 no tiene `ref.txt` | caché de HF | ~1.6 GB | MIT |

La caché de HF es `%USERPROFILE%\.cache\huggingface\hub` salvo que se defina `HF_HOME`/`HF_HUB_CACHE`.

> **Licencias (uso no comercial).** XTTS v2 se distribuye bajo la *Coqui Public Model
> License* (CPML) y los pesos de F5-TTS y del finetune `jpgallegoar/F5-Spanish` bajo
> CC-BY-NC-4.0: ninguno permite uso comercial. Al usar XTTS el programa acepta la CPML
> automáticamente (`COQUI_TOS_AGREED=1`).

### GPU o CPU

Los motores usan `cuda` si PyTorch ve una GPU y, si no, `cpu` (con un aviso de que irá lento).
`PODCAST_TTS_DEVICE=cpu|cuda` fuerza el dispositivo. La variante CUDA usa CUDA 12.6 (GPU desde
la serie GTX 900 hasta RTX 40).

Detalles de versiones, pins y problemas conocidos: [`docs/ENGINES.md`](docs/ENGINES.md).


## Estructura

```
AudioGeneration/
├── src/podcast_tts/
│   ├── script_parser.py   # parser del guion -> Segments (+ JSON)
│   ├── voices.py          # registro de voces en voices/
│   ├── assembler.py       # síntesis + mezcla + normalización + exportación
│   ├── cli.py             # python -m podcast_tts ...
│   ├── ui.py              # UI Gradio (python -m podcast_tts ui)
│   └── engines/
│       ├── base.py        # protocolo TTSEngine
│       ├── f5.py          # F5-TTS
│       ├── xtts.py        # XTTS v2
│       └── dummy.py       # motor de pruebas (tonos)
├── voices/<nombre>/       # ref.wav + ref.txt + voice.json
├── examples/ejemplo.md    # guion de ejemplo
├── guiones/               # guiones del usuario (ejemplo_dialogo.md: diálogo es/en)
├── bats/                  # install.bat, run.bat, update.bat, install_gpu.bat
├── scripts/               # check_env.py, install_skill.ps1, setup.ps1 (llama a bats\install.bat), smoke_*.py
├── skill/podcast-tts/     # skill de Claude Code (ver docs/SKILL.md)
├── docs/                  # ENGINES.md, DECISIONS.md, SKILL.md
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

Voces de ejemplo incluidas (generadas con `scripts/make_sample_voices.py` a partir de
speakers integrados de XTTS):

| Voz | Idioma | Motor | Origen |
|---|---|---|---|
| `ana` | es | f5 | clip de "Alma María" |
| `carlos` | es | f5 | clip de "Luis Moray" |
| `emma` | en | f5 | clip de "Claribel Dervla" |
| `david` | en | xtts | speaker integrado "Damien Black" (su `ref.wav` también vale para F5) |

### Añadir tu propia voz

```powershell
python -m podcast_tts voices add maria C:\grabaciones\maria.m4a `
    --text "Transcripción exacta, palabra por palabra, de lo que se oye en el clip." `
    --lang es --engine f5
```

Requisitos del clip:

- **5-15 s** (ideal 8-10 s; F5-TTS recorta a ~12 s y XTTS usa hasta ~15 s).
- **Limpio**: una sola persona, sin música, sin eco ni ruido de fondo, sin cortes a mitad de palabra.
- **Con transcripción exacta** (`--text`): F5-TTS la necesita para alinear. Si falta,
  se transcribe automáticamente con Whisper (descarga ~1.6 GB y es menos fiable).
- Cualquier formato que lea ffmpeg (wav, mp3, m4a...); se convierte solo.
- Graba en el idioma en que vaya a hablar la voz: F5 admite `es` y `en`; para otros
  idiomas usa `--engine xtts`.

### Speakers integrados de XTTS

XTTS v2 trae 58 voces listas para usar, sin clip (ver `podcast_tts.voices.XTTS_BUILTIN_SPEAKERS`
o `list_xtts_speakers()`). Algunas: "Claribel Dervla", "Ana Florence", "Alma María",
"Damien Black", "Luis Moray", "Marcos Rudaski". Hablan cualquiera de los 17 idiomas de XTTS:

```powershell
python -m podcast_tts voices add narrador --engine xtts --xtts-speaker "Marcos Rudaski" --lang es
```

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
$env:PYTHONUTF8='1'; $env:COQUI_TOS_AGREED='1'
.venv\Scripts\python.exe -m pytest           # rápido (~10 s): excluye los tests `slow`, sin cargar modelos
.venv\Scripts\python.exe -m pytest -m slow   # motores reales F5-TTS / XTTS v2 (GPU y modelos descargados, ~40 s)
```

`pytest` a secas aplica `-m 'not slow'` (configurado en `pyproject.toml`).
