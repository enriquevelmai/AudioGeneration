# Decisiones de diseño (2026-10-12)

- Motores TTS: F5-TTS (por defecto) y XTTS v2 (Coqui), seleccionables por voz.
- UI: Gradio en local.
- Formato de guion: Markdown con etiquetas, p.ej.
  `[voz:ana] Hola. [pausa:1.5] [voz:carlos lang=en] Hi. [musica:intro.mp3 vol=0.3]`
- Skill de Claude Code: global en `~/.claude/skills/podcast-tts`.
- Voces de ejemplo generadas automáticamente en `voices/` (el usuario añade las suyas).
- Hardware: Windows 11, RTX 4080 SUPER 16 GB, Python 3.11, uv, ffmpeg en PATH.
- Las voces de Microsoft/Edge-TTS NO funcionan (bloqueadas): no usarlas como dependencia.
