# Decisiones de diseño (2026-10-12)

- Motores TTS: F5-TTS (por defecto) y XTTS v2 (Coqui), seleccionables por voz.
- UI: Gradio en local.
- Formato de guion: Markdown con etiquetas, p.ej.
  `[voz:ana] Hola. [pausa:1.5] [voz:carlos lang=en] Hi. [musica:intro.mp3 vol=0.3]`
- Skill de Claude Code: global en `~/.claude/skills/podcast-tts`.
- Voces de ejemplo generadas automáticamente en `voices/` (el usuario añade las suyas).
- Hardware: Windows 11, RTX 4080 SUPER 16 GB, Python 3.11, uv, ffmpeg en PATH.
- Las voces de Microsoft/Edge-TTS NO funcionan (bloqueadas): no usarlas como dependencia.

## Decisiones tomadas durante la implementación

- **F5 por idioma**: `lang=en` usa el modelo oficial `F5TTS_v1_Base`; `lang=es` usa el finetune
  comunitario `jpgallegoar/F5-Spanish` (arquitectura `F5TTS_Base`, CC-BY-NC-4.0), porque el modelo
  base (inglés/chino) pronuncia el castellano con acento. Otros idiomas → XTTS.
- **torch fijado a 2.8** (`torch==2.8.*`, `torchaudio==2.8.*`, cu126): desde 2.9 `torchaudio.load`
  delega en torchcodec, que en Windows necesita las DLL compartidas de FFmpeg (el ffmpeg de
  chocolatey es estático) y rompe F5 y XTTS. Ver `docs/ENGINES.md`.
- **Voces de ejemplo** (`ana`, `carlos`, `emma`, `david`) generadas con speakers integrados de XTTS
  (`scripts/make_sample_voices.py`), para no depender de grabaciones externas; el usuario añade las suyas.
- **Caché de síntesis** en `.cache/tts/<sha256>.npz` (clave: texto, huella de la voz, idioma,
  velocidad, motor). Ignorada por git; al editar el guion solo se resintetizan las frases cambiadas.
- **Semilla `None` por defecto**: F5 (y XTTS, que muestrea) producen una toma distinta en cada
  síntesis; una regeneración solo es idéntica gracias a la caché (`--no-cache` da otra toma).

## Motores en la nube, plugins y licencias (2026-10-14)

- **Licencias**: los pesos de F5-TTS / F5-Spanish (CC-BY-NC-4.0) y XTTS v2 (CPML) son de uso no
  comercial. Cada motor declara `license_info` (`LicenseInfo`); la CLI avisa una vez al generar con
  un motor no comercial (`--no-license-notice` lo oculta) y la UI muestra un aviso discreto.
- **Motores en la nube de pago** (`elevenlabs`, `azure`, `openai`) con solo la stdlib
  (`urllib.request`), pidiendo PCM 24 kHz directamente; sin SDKs ni dependencias nuevas.
  `azure` es Azure AI Speech con clave propia, no Edge-TTS (que sigue sin usarse).
- **Claves** en variables de entorno o en `.env` (ignorado por git); las del entorno tienen
  prioridad. Nunca se imprimen: se muestran enmascaradas (`sk-...abcd`).
- **Plugins**: motores de terceros por entry points del grupo `podcast_tts.engines`; los nombres
  de motor válidos son dinámicos (`engines.engine_names()`). Ver `docs/ENGINES_PLUGINS.md`.
- **Voces cloud**: `voice.json` con `provider_voice_id` y `provider_options`, sin `ref.wav`. La
  huella de caché solo cambia para voces que tengan esos campos (las locales conservan su caché).
- Detalles de uso comercial: `docs/COMMERCIAL_USE.md`.
