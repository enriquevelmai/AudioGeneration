# Registro de decisiones técnicas

Decisiones de diseño de AudioGeneration (`podcast_tts`) y su motivo. Para el detalle de versiones
y pins, ver [ENGINES.md](ENGINES.md); para licencias, [MODELS_AND_LICENSES.md](../MODELS_AND_LICENSES.md).

## Alcance

- **Plataforma**: Windows 10/11 x64, Python 3.11 gestionado por uv, ffmpeg en el `PATH`. GPU NVIDIA
  recomendada; la CPU funciona como alternativa más lenta. Entorno de referencia: Windows 11 con una
  RTX 4080 SUPER de 16 GB.
- **Formato de guion**: Markdown con etiquetas en línea, p.ej.
  `[voz:ana] Hola. [pausa:1.5] [voz:carlos lang=en] Hi. [musica:intro.mp3 vol=0.3]`. Es texto plano
  legible, fácil de versionar y de escribir a mano o con un asistente.
- **Interfaz**: CLI y UI web local con Gradio, ambas en castellano. La app de escritorio
  (`podcast-tts desktop`, extra `desktop`) muestra la misma UI en una ventana nativa con pywebview.
- **Skill de Claude Code**: versionada en `skill/podcast-tts/` e instalada como junction en
  `~/.claude/skills/podcast-tts` (ver [SKILL.md](SKILL.md)). Es opcional.
- **Voces de ejemplo** generadas automáticamente en `voices/`; el usuario añade las suyas.
- **Sin Edge-TTS**: no se usa el endpoint no oficial de lectura en voz alta de Microsoft Edge
  (`edge-tts`) ni las voces SAPI del sistema. La opción oficial de Microsoft es el motor `azure`
  (Azure AI Speech de pago, con clave propia).

## Motores locales

- **F5-TTS por defecto, F5 por idioma**: `lang=en` usa el modelo oficial `F5TTS_v1_Base`; `lang=es`
  usa el finetune comunitario `jpgallegoar/F5-Spanish` (arquitectura `F5TTS_Base`, CC-BY-NC-4.0),
  porque el modelo base (inglés/chino) pronuncia el castellano con acento. Otros idiomas → XTTS v2.
- **torch fijado a 2.8** (`torch==2.8.*`, `torchaudio==2.8.*`, cu126): desde 2.9 `torchaudio.load`
  delega en torchcodec, que en Windows necesita las DLL compartidas de FFmpeg (las builds habituales
  de ffmpeg son estáticas) y rompe F5 y XTTS.
- **transformers < 5**: coqui-tts 0.27 importa una función eliminada en transformers 5.
- **Un único `.venv`** para F5-TTS y coqui-tts: conviven con los pins anteriores.
- **Voces de ejemplo** (`ana`, `carlos`, `emma`, `david`) generadas con speakers integrados de XTTS
  (`scripts/make_sample_voices.py`), para no depender de grabaciones externas. Heredan la licencia
  no comercial de XTTS v2.
- **Caché de síntesis** en `.cache/tts/<sha256>.npz` (clave: texto, huella de la voz, idioma,
  velocidad, motor). Al editar el guion solo se resintetizan las frases cambiadas.
- **Semilla `None` por defecto**: F5 y XTTS muestrean, así que cada síntesis es una toma distinta;
  una regeneración solo es idéntica gracias a la caché (`--no-cache` da otra toma).

## Instalación por capas

- **Núcleo sin torch** (parser, motor `dummy`, CLI, UI, `models`, tests rápidos) y extras de uv:
  `local` (F5-TTS y XTTS v2), `cuda` / `cpu` (variante de PyTorch, mutuamente excluyentes), `dev`
  (pytest) y `desktop` (pywebview). La CI instala solo el núcleo.
- **`uv.lock` para todo**: `bats\install.bat` instala uv y Python 3.11 sin permisos de administrador
  y ejecuta `uv sync --locked`; los extras elegidos se guardan en `.venv\podcast-tts-extras.txt` para
  que `bats\update.bat` los reutilice.
- **Dispositivo automático**: `cuda` si PyTorch ve una GPU, si no `cpu`; `PODCAST_TTS_DEVICE` lo
  fuerza.
- **Modelos fuera del repositorio**: se descargan de Hugging Face a las cachés estándar (HF y coqui)
  la primera vez o con `podcast-tts models download`; `models update` baja la última revisión.

## Motores en la nube, plugins y licencias

- **Licencias explícitas**: cada motor declara `license_info` (`LicenseInfo`). La CLI avisa una vez
  al generar con un motor no comercial (`--no-license-notice` lo oculta) y la UI muestra un aviso
  discreto. Los plugins que no declaran licencia se tratan como no comerciales.
- **Motores en la nube de pago** (`elevenlabs`, `azure`, `openai`) con solo la biblioteca estándar
  (`urllib.request`), pidiendo PCM 24 kHz directamente; sin SDKs ni dependencias nuevas.
- **Claves** en variables de entorno o en `.env` (ignorado por git); las del entorno tienen
  prioridad. Nunca se imprimen: se muestran enmascaradas (`sk-...abcd`).
- **Plugins** de terceros por entry points del grupo `podcast_tts.engines`; los nombres de motor
  válidos son dinámicos (`engines.engine_names()`). Ver [ENGINES_PLUGINS.md](ENGINES_PLUGINS.md).
- **Voces cloud**: `voice.json` con `provider_voice_id` y `provider_options`, sin `ref.wav`. La
  huella de caché solo cambia para voces que tengan esos campos (las locales conservan su caché).
- Detalles de uso comercial: [COMMERCIAL_USE.md](COMMERCIAL_USE.md).

## Distribución (1.0.0)

- **Release para Windows**: `AudioGeneration-v1.0.0-windows.zip` con el código, los scripts de
  `bats\` y el lanzador `AudioGeneration.exe` (generado con `bats\build_launcher.bat`). No incluye
  `.venv` ni modelos: el lanzador instala el entorno la primera vez.
- **Actualizaciones desde el lanzador**: en un clon de git busca cambios con git; en una descarga
  zip consulta la última release de GitHub.
- **Arranque**: `bats\run.bat` abre la app de escritorio y, si falta pywebview, cae al navegador;
  `bats\run_web.bat` abre siempre el navegador. `bats\create_shortcuts.bat` crea los accesos del
  Escritorio y del menú Inicio (lo ofrece `bats\install.bat`).
- **Licencia**: el código es MIT; los pesos de los modelos conservan sus propias licencias.

## Robustez y seguridad (revisión posterior a 1.0.0)

- **Rutas con acentos**: Python 3.11 lee los `.pth` con la codificación ANSI de Windows aunque
  `PYTHONUTF8=1`, así que la instalación editable de uv fallaba en `C:\Users\José\...`. Se
  descartó `uv sync --no-editable` porque el código localiza el proyecto con
  `Path(__file__).parents[2]` (voces, ejemplos, `.env`) y obligaría a reinstalar el paquete en
  cada actualización. En su lugar, `scripts/fix_editable_pth.py` reescribe el `.pth` como una
  línea `import` solo ASCII que calcula `<proyecto>\src` desde `sys.prefix`; los `.bat` y el
  lanzador definen además `PYTHONPATH`.
- **UI remota**: fuera de `127.0.0.1` o con `--share` la UI exige `--auth` y funciona en modo
  remoto (sin pestaña Ajustes y sin rutas de audio absolutas). Los eventos internos son privados
  en la API de Gradio (`api_visibility="private"`).
- **Caché de síntesis**: la clave incluye el `cache_tag` de cada motor (modelo, versión del
  paquete y parámetros), de modo que cambiar de modelo regenera las frases.
- **Instancia única**: el mutex lleva un hash de la carpeta del proyecto (varias instalaciones
  pueden convivir) y el lanzador lo consulta para no actualizar con la app abierta.
