@echo off
REM ====================================================================
REM  podcast-tts - Integrations with AI assistants (MCP server).
REM
REM  - Installs the mcp extra if missing (uv sync with the same extras).
REM  - Claude Code: podcast-tts skill + "claude mcp add --scope user podcast-tts".
REM  - Claude Desktop: podcast-tts entry in claude_desktop_config.json
REM    (merges without deleting other entries; writes a .bak copy first).
REM  - Other clients (Cursor, VS Code...): prints the JSON to paste.
REM  It is idempotent: it can be run as many times as needed.
REM
REM  Usage: bats\install_integrations.bat                  (detects and asks)
REM         bats\install_integrations.bat /y               (everything detected, no questions)
REM         bats\install_integrations.bat /claude-code     (Claude Code only)
REM         bats\install_integrations.bat /claude-desktop  (Claude Desktop only)
REM         bats\install_integrations.bat /print           (only prints the JSON)
REM         bats\install_integrations.bat --uninstall      (removes the registration)
REM  Testing: --dry-run (changes nothing), --config-path FILE (another Desktop config)
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
    echo ERROR: .venv does not exist. Run bats\install.bat first
    if not "%NONINTERACTIVE%"=="1" pause
    endlocal
    exit /b 1
)

".venv\Scripts\python.exe" scripts\install_integrations.py %*
set "RC=%ERRORLEVEL%"
if not "%NONINTERACTIVE%"=="1" pause
endlocal & exit /b %RC%
