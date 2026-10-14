# Skill de Claude Code `podcast-tts`

La skill que permite a Claude Code generar podcasts con este proyecto vive versionada en
`skill/podcast-tts/`:

```
skill/podcast-tts/
├── SKILL.md                      # instrucciones + front matter (name, description)
├── references/formato-guion.md   # formato completo del guion y 3 ejemplos
└── scripts/
    ├── generar.ps1               # wrapper del CLI para PowerShell
    └── generar.sh                # wrapper del CLI para Git Bash (y Linux)
```

La skill es portable: no contiene rutas de ningún usuario. Los wrappers localizan la raíz del
proyecto por este orden:

1. la variable de entorno `PODCAST_TTS_HOME`;
2. el destino de la junction `%USERPROFILE%\.claude\skills\podcast-tts` (`<repo>\skill\podcast-tts` -> `<repo>`);
3. la ruta relativa `../../..` desde el propio script (si se ejecuta dentro del repositorio).

Después fijan `PYTHONUTF8`, `PYTHONIOENCODING` y `COQUI_TOS_AGREED`, y ejecutan
`<repo>\.venv\Scripts\python.exe -m podcast_tts <argumentos>`. `generar.ps1 --where` /
`generar.sh --where` imprimen la raíz encontrada.

## Instalación

`bats\install.bat` ofrece instalarla si existe `%USERPROFILE%\.claude` (es decir, si usas Claude Code).
A mano:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1          # junction (idempotente)
powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -Copy    # copia, si la junction no es posible
```

Por defecto crea una **junction** de directorio (no requiere administrador):

```
%USERPROFILE%\.claude\skills\podcast-tts  ->  <repo>\skill\podcast-tts
```

Al ser una junction, cualquier cambio en `skill/podcast-tts/` del repo se refleja al instante en
Claude Code (en sesiones nuevas), y los wrappers encuentran el proyecto siguiendo el enlace.

El script no hace nada si la junction ya es correcta, la recrea si apunta a otra ruta (salvo con
`-NoReplace`, que usa el instalador en modo `/y`) y, si encuentra una carpeta normal (copia
antigua), la renombra a `podcast-tts.bak-<fecha>` antes de enlazar.

Con `-Copy` copia la carpeta y, como una copia no sabe dónde está el proyecto, fija además la
variable de usuario `PODCAST_TTS_HOME` con la raíz del repositorio. Hay que volver a ejecutarlo
tras cada cambio de la skill.

Si se mueve el repositorio, vuelve a ejecutar el script (o actualiza `PODCAST_TTS_HOME`).

Desinstalar: `cmd /c rmdir %USERPROFILE%\.claude\skills\podcast-tts` (borra solo el enlace).
