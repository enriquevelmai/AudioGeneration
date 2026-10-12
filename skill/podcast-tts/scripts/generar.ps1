<#
.SYNOPSIS
  Wrapper del CLI de podcast_tts: fija las variables de entorno y pasa todos los argumentos.

.EXAMPLE
  & "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" voices list --json
  & "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" parse guiones\episodio.md
  & "$HOME\.claude\skills\podcast-tts\scripts\generar.ps1" generate guiones\episodio.md -o output\episodio.mp3
#>
$ErrorActionPreference = 'Stop'

$Project = if ($env:PODCAST_TTS_HOME) { $env:PODCAST_TTS_HOME } else { 'C:\Users\enriq\Documents\claude\AudioGeneration' }
$Python = Join-Path $Project '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Write-Error "No se encuentra $Python. Ejecuta scripts\setup.ps1 en $Project."
    exit 2
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:COQUI_TOS_AGREED = '1'

& $Python -m podcast_tts @args
exit $LASTEXITCODE
