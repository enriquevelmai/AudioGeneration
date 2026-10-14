# Formato de guion de podcast_tts (referencia completa)

Fuente de verdad: `src/podcast_tts/script_parser.py`. Ante cualquier duda, `python -m podcast_tts parse guion.md`.

## 1. Fichero

- Markdown en UTF-8 (con o sin BOM), extensión `.md`. Saltos de línea `\n` o `\r\n`.
- Opcionalmente empieza con un front matter entre líneas `---` (cierre con `---` o `...`).
- El resto es texto hablado con etiquetas `[tipo:valor atributos]` intercaladas, en cualquier posición
  de la línea (una línea puede tener varias etiquetas y texto entre ellas).

## 2. Front matter

| Clave | Alias | Tipo | Efecto |
|---|---|---|---|
| `title` | `titulo`, `título` | texto | Título (metadato) |
| `lang` | `idioma` | código | Idioma por defecto del guion (`es`, `en`, `fr`...) |
| `default_voice` | `voz`, `voice` | nombre | Voz para el texto que aparece antes de cualquier `[voz:]` |
| `engine` | `motor`, `default_engine` | `f5`/`xtts` | Motor por defecto del guion |
| `paragraph_pause` | `pausa_parrafo` | número (s) | Pausa al cambiar de párrafo (0.4 por defecto) |

Claves desconocidas o valores inválidos producen error.

## 3. Etiquetas

Los nombres de etiqueta no distinguen mayúsculas. Atributos `clave=valor` separados por espacios;
valores con espacios entre comillas.

### `[voz:nombre ...]` (alias `[voice:]`)
Cambia el hablante desde ese punto hasta la siguiente `[voz:]`. Cada `[voz:]` reinicia los atributos
(no se heredan `lang`/`speed` de la anterior).
- `lang=xx`: idioma de este tramo.
- `speed=N`: velocidad (0.25-4.0; 1.0 normal; 0.9-1.1 es lo razonable).
- `engine=f5|xtts`: motor para este tramo.
Ejemplo: `[voz:carlos lang=en speed=0.95 engine=xtts]`

### `[pausa:N]` (alias `[pause:]`)
Silencio de N segundos (admite sufijo `s`: `[pausa:2s]`). Solo un valor.

### `[musica:ruta ...]` (alias `[music:]`, `[música:]`)
- Sin flag: inserta el clip completo en ese punto y el tiempo avanza su duración.
  `vol=0-1` (por defecto 1.0), `fade=s` (por defecto 0).
- Con flag `fondo` / `bg` / `background` (o `fondo=true`): música de fondo en bucle bajo las voces
  siguientes, con ducking automático. `vol` por defecto 0.15, `fade` por defecto 1.5.
- `[musica:stop]` (o `fin`, `parar`): detiene la música de fondo; `fade` por defecto 1.5.
- `volume=` es sinónimo de `vol=`.

### `[sfx:ruta vol=N]`
Efecto superpuesto desde ese punto; NO avanza el tiempo. `vol` por defecto 1.0.

### `[titulo:texto]` (alias `[title:]`, `[título:]`)
Fija el título (metadato); no se sintetiza.

## 4. Reglas de procesado

- Línea que empieza (tras espacios) por `#`: comentario completo, aunque contenga etiquetas.
- `<!-- ... -->`: comentario HTML; puede ocupar varias líneas o ir en mitad de una, y no suena.
  Un `<!--` sin cerrar es un error.
- Los corchetes que no son `[tipo:...]` (casillas `- [ ]`, `[risas]`) se leen como texto, y los
  enlaces `[texto](url)` se leen como "texto". `[palabra:...]` con un tipo desconocido es error.
  Útil para estructura (`# Sección 2`) y para desactivar música (`# [musica:intro.mp3]`).
- Línea vacía: termina el párrafo e inserta `paragraph_pause` antes del siguiente texto.
- Saltos de línea simples dentro de un párrafo se unen con espacio.
- El texto se divide en frases (`. ! ? …` y saltos de línea) y se agrupa en trozos de hasta
  `--max-chars` (250) sin partir frases; una frase más larga se corta por comas/espacios (evítalo).
- Rutas de audio relativas al fichero del guion (o absolutas). Formatos: cualquiera que lea ffmpeg.
- Errores (etiqueta desconocida, atributo inválido, número fuera de rango, front matter mal formado,
  texto sin voz) → `Error en el guion: ...` con número de línea; el comando sale con código 1.

### Prioridades
- Idioma: `[voz: lang=]` > `lang` del front matter > `lang` de `voice.json`.
- Motor: `--engine` del CLI > `[voz: engine=]` > `engine` del front matter > `engine` de `voice.json`.
- Velocidad: `[voz: speed=]` > `speed` de `voice.json`.

## 5. Ejemplos

Los nombres de voz (`ana`, `carlos`, `narrador`) son ilustrativos: sustitúyelos por voces reales de
`python -m podcast_tts voices list --json`.

### 5.1 Monólogo corto

```markdown
---
title: Consejo del día
lang: es
default_voice: ana
---

Hola, soy Ana y esto es el consejo del día.

Hoy hablamos de algo sencillo: beber agua. Los expertos recomiendan entre un litro y medio y dos litros
al día. No hace falta obsesionarse, basta con tener siempre una botella a mano.

[pausa:0.8]
Eso es todo por hoy. ¡Hasta mañana!
```

### 5.2 Diálogo bilingüe con música de fondo

```markdown
---
title: Puente de idiomas - Episodio 1
lang: es
engine: f5
---

# Intro: sintonía completa y luego fondo suave (rutas relativas a este guion)
[musica:assets/intro.mp3 vol=0.7 fade=1]
[musica:assets/fondo.mp3 fondo vol=0.12 fade=2]

[voz:ana]
¡Bienvenidos a Puente de idiomas! Hoy me acompaña Carlos, que vive en Londres desde hace diez años.

[voz:carlos]
Hola, Ana. Gracias por invitarme. Hoy vamos a practicar algunas frases útiles para viajar.

[voz:carlos lang=en]
Excuse me, could you tell me where the train station is?

[voz:ana]
Perfecto. Eso significa: perdone, ¿podría decirme dónde está la estación de tren?

[voz:ana lang=en speed=0.9]
Thank you very much. Have a nice day!

[pausa:1]
[voz:carlos]
Y hasta aquí el episodio de hoy. ¡Nos escuchamos la semana que viene!

[musica:stop fade=3]
[pausa:1.5]
```

### 5.3 Noticias con varias secciones

```markdown
---
title: Resumen de noticias del lunes
lang: es
default_voice: narrador
paragraph_pause: 0.5
---

[musica:assets/cabecera.mp3 vol=0.8 fade=0.5]

Buenos días. Son las ocho de la mañana del lunes doce de octubre y este es el resumen de noticias.

[pausa:1.2]
# ---------- Sección 1: Tecnología ----------
[sfx:assets/transicion.wav vol=0.6]
[voz:ana]
Empezamos con tecnología. Una nueva generación de modelos de voz permite crear podcasts completos
en un ordenador doméstico, sin depender de servicios en la nube.

Según sus desarrolladores, la calidad ya es comparable a la de una locución profesional.

[pausa:1.2]
# ---------- Sección 2: Economía ----------
[sfx:assets/transicion.wav vol=0.6]
[voz:carlos]
En economía, la inflación se moderó en septiembre hasta el dos coma uno por ciento,
tres décimas menos que en agosto.

[pausa:1.2]
# ---------- Sección 3: El tiempo ----------
[sfx:assets/transicion.wav vol=0.6]
[voz:narrador speed=1.05]
Y el tiempo: cielos despejados en casi todo el país, con máximas de veinticuatro grados en el sur.

[pausa:1]
Esto ha sido todo. Gracias por escucharnos y feliz semana.
[musica:assets/cierre.mp3 vol=0.7 fade=2]
```
