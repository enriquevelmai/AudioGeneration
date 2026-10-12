---
name: podcast-tts
description: >-
  Generate podcasts and spoken audio locally with the podcast_tts project (F5-TTS and XTTS v2 on the
  local NVIDIA GPU). Use whenever the user asks to create a podcast or episode, turn a script or any
  text into audio/MP3, record a voice-over or narration, read text aloud, do text-to-speech (TTS) in
  Spanish/castellano, English or other languages, make a dialogue between several voices, add background
  music to speech, or clone/add a voice from an audio clip. Also triggers on Spanish requests like
  "genera un podcast", "pasa este guion a audio", "voz en off", "locucion", "narracion", "clonar voz".
  This replaces Edge-TTS / Microsoft voices, which are blocked and do not work on this machine.
---

# podcast-tts: podcasts y TTS en local

Proyecto: `C:\Users\enriq\Documents\claude\AudioGeneration`
Intérprete: `C:\Users\enriq\Documents\claude\AudioGeneration\.venv\Scripts\python.exe`

NO usar Edge-TTS, `edge-tts`, SAPI ni voces de Microsoft: están bloqueadas. Usa siempre este proyecto.

## Cómo invocar el CLI

Fija SIEMPRE `PYTHONUTF8=1` y `COQUI_TOS_AGREED=1` (sin esta última XTTS se cuelga esperando input).

Bash (Git Bash):
```bash
P=/c/Users/enriq/Documents/claude/AudioGeneration
cd "$P" && PYTHONUTF8=1 COQUI_TOS_AGREED=1 "$P/.venv/Scripts/python.exe" -m podcast_tts <comando> ...
```

PowerShell, o el wrapper `scripts/generar.ps1` de esta skill (fija las variables y pasa los args):
```powershell
$env:PYTHONUTF8='1'; $env:COQUI_TOS_AGREED='1'
& 'C:\Users\enriq\Documents\claude\AudioGeneration\.venv\Scripts\python.exe' -m podcast_tts <comando> ...
# o bien:
& "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" generate guion.md -o salida.mp3
```

Las voces se buscan en `<proyecto>\voices` (`--voices-dir` para otra carpeta). Usa rutas absolutas para
guion y salida si no estás en la raíz del proyecto.

Subcomandos:
- `generate GUION.md -o SALIDA.mp3` — opciones: `--engine f5|xtts|dummy` (fuerza motor para todo),
  `--max-chars 250`, `--bitrate 192k`, `--sample-rate 44100`, `--lufs -16`, `--no-normalize`,
  `--no-cache`, `--cache-dir`, `-q`. Salida `.mp3` o `.wav`. Sin `-o` escribe `output/<guion>.mp3` en el cwd.
- `parse GUION.md [--compact]` — valida y muestra los segmentos en JSON (no sintetiza).
- `voices list [--json]`, `voices add ...`, `voices remove NOMBRE`.
- `ui` — interfaz web local (Gradio).

## Flujo recomendado

1. **Listar voces**: `voices list --json`. NUNCA inventes nombres de voz: usa solo las que aparecen
   (mira `name`, `lang`, `engine`, `has_ref`, `xtts_speaker`, `description`). Si ninguna encaja,
   pregunta al usuario o crea una (ver "Añadir una voz").
2. **Escribir el guion** `.md` (UTF-8) en `C:\Users\enriq\Documents\claude\AudioGeneration\guiones\`
   (créala si no existe) o en el cwd del usuario si lo prefiere. Sigue los consejos de redacción.
3. **Validar**: `parse guion.md`. Corrige cualquier error (da número de línea) y comprueba que cada
   segmento `speech` tenga la voz e idioma esperados. `"lang": null` en un segmento significa "sin
   etiqueta `lang=`": se usará el `lang` del front matter si lo hay y, si no, el de `voice.json`.
4. **Generar**: `generate guion.md -o <ruta>.mp3` (por defecto en `...\AudioGeneration\output\`).
   Para probar tiempos y mezcla sin GPU: `--engine dummy` (tonos en lugar de voz).
5. **Reportar** la ruta absoluta del fichero y su duración:
   `ffprobe -v error -show_entries format=duration -of csv=p=0 salida.mp3`
   (el `Listo: ... (N s)` final del CLI es el tiempo de generación, no la duración del audio).

Al regenerar tras editar el guion, la caché (`.cache/tts`) solo resintetiza las frases cambiadas.

## Formato del guion (resumen)

Front matter opcional al principio del fichero:
```markdown
---
title: Mi episodio
lang: es              # idioma por defecto (alias: idioma)
default_voice: ana    # voz para el texto sin [voz:] previa (alias: voz, voice)
engine: f5            # f5 | xtts (alias: motor, default_engine)
paragraph_pause: 0.4  # pausa entre párrafos en s (alias: pausa_parrafo)
---
```

| Etiqueta | Alias | Efecto | Atributos / ejemplo |
|---|---|---|---|
| `[voz:nombre]` | `[voice:]` | Cambia de hablante hasta la siguiente `[voz:]` | `lang=en`, `speed=0.25-4`, `engine=f5\|xtts` → `[voz:carlos lang=en speed=1.05]` |
| `[pausa:1.5]` | `[pause:]` | Silencio de N s (`1.5` o `1.5s`) | `[pausa:0.8]` |
| `[musica:ruta]` | `[music:]`, `[música:]` | Clip musical que avanza el tiempo | `vol=0-1` (1.0), `fade=s` (0) → `[musica:intro.mp3 vol=0.6 fade=1]` |
| `[musica:ruta fondo]` | flag `bg`/`background`, o `fondo=true` | Música de fondo en bucle bajo las voces, con ducking | `vol` (0.15), `fade` (1.5) → `[musica:fondo.mp3 fondo vol=0.12]` |
| `[musica:stop]` | `fin`, `parar` | Para la música de fondo con fundido | `fade` (1.5) → `[musica:stop fade=3]` |
| `[sfx:ruta]` | — | Efecto superpuesto; no avanza el tiempo | `vol` (1.0) → `[sfx:ding.wav vol=0.7]` |
| `[titulo:texto]` | `[title:]`, `[título:]` | Metadato; no suena | `[titulo:Episodio 3]` |

Reglas clave:
- Líneas que empiezan por `#` o `<!--` son comentarios (no suenan aunque tengan etiquetas).
- Línea en blanco = nuevo párrafo + pausa corta (0.4 s).
- Rutas de música/sfx relativas al guion o absolutas; con espacios, entre comillas: `[musica:"mis audios/a.mp3"]`.
- Etiqueta o atributo desconocido → error con número de línea.
- Prioridades: **idioma** = etiqueta > front matter > `voice.json`; **motor** = `--engine` > etiqueta >
  front matter > `voice.json`; **velocidad** = etiqueta > `voice.json`.
- Texto antes de cualquier `[voz:]` y sin `default_voice` → error.
- **Guiones bilingües**: NO pongas `lang` en el front matter (forzaría ese idioma a todas las voces,
  p.ej. `emma` leería inglés con el modelo castellano). Deja que cada voz use el `lang` de su
  `voice.json`, o indícalo por tramo: `[voz:ana lang=en]`.

Referencia completa y 3 guiones de ejemplo: `references/formato-guion.md` (léela si el guion usa música,
varios idiomas o varias secciones).

## Consejos de redacción para TTS

- Frases cortas y completas, cada una < 250 caracteres (se trocea por `. ! ? …`).
- Números, fechas, horas y cantidades en letras: "dos mil veintiséis", "las nueve y media", "un quince por ciento".
- Expande abreviaturas y siglas: "por ejemplo" (no "p. ej."), "señor" (no "Sr."); URLs dichas en palabras.
- La puntuación marca el ritmo: comas = respiración, punto = pausa; usa `¿?` y `¡!` en castellano.
- Nada de emojis, markdown (`**`, viñetas, enlaces), tablas ni código en el texto hablado.
  Los encabezados `#` sirven como comentarios de estructura.
- Separa secciones con `[pausa:1]`–`[pausa:1.5]`; alterna voces para dar dinamismo.
- Otro idioma: `[voz:x lang=en]` en lugar de mezclar idiomas dentro de una frase.

## F5 vs XTTS

- **f5 (por defecto)**: mejor calidad clonando en castellano e inglés. Requiere `ref.wav` + `ref.txt`
  con la transcripción exacta del clip.
- **xtts**: para los otros 15 idiomas (fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, hu, ko, ja, hi) o
  para usar uno de los 58 speakers integrados sin clip (p.ej. "Ana Florence", "Claribel Dervla",
  "Alma María", "Luis Moray"). Estocástico (la duración varía); límite ~239 caracteres por frase en `es`.

## Añadir una voz

```bash
# Clonada: clip de 5-15 s, limpio, sin música, y su transcripción EXACTA
... -m podcast_tts voices add lucia "C:/ruta/clip.wav" --text "Transcripción exacta del clip." --lang es --engine f5 --description "mujer, cálida"
#   (--text-file trans.txt en vez de --text; --speed 1.05; --overwrite para reemplazar)
# Speaker integrado de XTTS (sin clip):
... -m podcast_tts voices add narrador --engine xtts --xtts-speaker "Claribel Dervla" --lang en
```
Queda en `voices/<nombre>/` (`ref.wav` mono 24 kHz, `ref.txt`, `voice.json`). Nombre: letras, números, `_` o `-`.
Confirma después con `voices list`.

## Tiempos esperados (RTX 4080 SUPER)

- Primera carga del modelo: 10-30 s (XTTS ~10 s en caché, ~30 s si descarga; F5 unos segundos).
- Después ~0.2-0.3× tiempo real: un episodio de 10 min tarda ~2-3 min. Para guiones largos usa
  timeout amplio (p.ej. 600000 ms) o ejecútalo en segundo plano.

## Errores comunes

- **Voz no encontrada**: `voices list --json` y usa un nombre real, o crea la voz.
- **"Error en el guion: ... (línea N)"**: corrige la etiqueta/atributo de esa línea y repite `parse`.
- **Texto sin voz**: añade `default_voice` en el front matter o una `[voz:]` antes del texto.
- **ffmpeg / "no se pudo leer el audio"**: ffmpeg debe estar en PATH (`ffmpeg -version`); revisa la ruta
  de música/sfx (relativa al guion, no al cwd).
- **CUDA no disponible / out of memory**: `.venv\Scripts\python.exe scripts\check_env.py`; cierra otros
  procesos que usen la GPU (p.ej. la UI abierta) y reintenta. `--engine dummy` para probar sin GPU.
- **XTTS se queda colgado al cargar**: falta `COQUI_TOS_AGREED=1`.
- **UnicodeEncodeError**: falta `PYTHONUTF8=1`.
- Entorno roto: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` en la raíz del proyecto.

## UI

`... -m podcast_tts ui` lanza la interfaz web local (Gradio). Ejecútala en segundo plano y pasa al
usuario la URL que imprime (normalmente http://127.0.0.1:7860).
