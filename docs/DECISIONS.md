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
