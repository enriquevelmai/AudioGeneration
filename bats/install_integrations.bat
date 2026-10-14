@echo off
REM ====================================================================
REM  podcast-tts - Integraciones con asistentes de IA (servidor MCP).
REM
REM  - Instala el extra mcp si falta (uv sync con los mismos extras).
REM  - Claude Code: skill podcast-tts + "claude mcp add --scope user podcast-tts".
REM  - Claude Desktop: entrada podcast-tts en claude_desktop_config.json
REM    (fusiona sin borrar otras entradas; copia .bak antes de escribir).
REM  - Otros clientes (Cursor, VS Code...): imprime el JSON para pegar.
REM  Es idempotente: se puede ejecutar las veces que haga falta.
REM
REM  Uso:   bats\install_integrations.bat                  (detecta y pregunta)
REM         bats\install_integrations.bat /y               (todo lo detectado, sin preguntas)
REM         bats\install_integrations.bat /claude-code     (solo Claude Code)
REM         bats\install_integrations.bat /claude-desktop  (solo Claude Desktop)
REM         bats\install_integrations.bat /print           (solo imprime el JSON)
REM         bats\install_integrations.bat --uninstall      (quita el registro)
REM  Pruebas: --dry-run (no cambia nada), --config-path FICHERO (otro config de Desktop)
REM ====================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"

set "NONINTERACTIVE=0"
for %%a in (%*) do (
    if /i "%%~a"=="/y" set "NONINTERACTIVE=1"
    if /i "%%~a"=="-y" set "NONINTERACTIVE=1"
    if /i "%%~a"=="/print" set "NONINTERACTIVE=1"
)

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no existe .venv. Ejecuta primero bats\install.bat
    if not "%NONINTERACTIVE%"=="1" pause
    endlocal
    exit /b 1
)

".venv\Scripts\python.exe" scripts\install_integrations.py %*
set "RC=%ERRORLEVEL%"
if not "%NONINTERACTIVE%"=="1" pause
endlocal & exit /b %RC%
