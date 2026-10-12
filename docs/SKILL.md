# Skill de Claude Code `podcast-tts`

La skill que permite a Claude Code generar podcasts con este proyecto vive versionada en
`skill/podcast-tts/`:

```
skill/podcast-tts/
├── SKILL.md                      # instrucciones + front matter (name, description)
├── references/formato-guion.md   # formato completo del guion y 3 ejemplos
└── scripts/generar.ps1           # wrapper del CLI (fija PYTHONUTF8 y COQUI_TOS_AGREED)
```

## Instalación

Está instalada de forma global mediante una **junction** de directorio (no requiere administrador):

```
C:\Users\enriq\.claude\skills\podcast-tts  ->  C:\Users\enriq\Documents\claude\AudioGeneration\skill\podcast-tts
```

Al ser una junction, cualquier cambio en `skill/podcast-tts/` del repo se refleja al instante en
Claude Code (en sesiones nuevas). No hay que copiar nada.

## Reinstalar / reparar

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1          # junction (idempotente)
powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -Copy    # copia, si la junction no es posible
```

El script no hace nada si la junction ya es correcta, la recrea si apunta a otra ruta y, si encuentra
una carpeta normal (copia antigua), la renombra a `podcast-tts.bak-<fecha>` antes de enlazar.
Con `-Copy` hay que volver a ejecutarlo tras cada cambio de la skill.

Si se mueve el repositorio, vuelve a ejecutar el script y actualiza las rutas absolutas de
`skill/podcast-tts/SKILL.md` y `scripts/generar.ps1` (o define `PODCAST_TTS_HOME`).

Desinstalar: `cmd /c rmdir %USERPROFILE%\.claude\skills\podcast-tts` (borra solo el enlace).
