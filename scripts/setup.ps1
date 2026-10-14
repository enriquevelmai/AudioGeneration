<#
.SYNOPSIS
  Compatibilidad: la instalacion vive en bats\install.bat. Este script solo lo llama.

.DESCRIPTION
  Ejecuta bats\install.bat en modo no interactivo (detecta GPU NVIDIA, uv sync con
  los extras local + cuda|cpu + desktop, check_env). No descarga modelos ni instala la skill
  salvo que se pida.
  - -Recreate: borra .venv antes de instalar.
  - -Smoke: ademas descarga los modelos y genera output\smoke_*.wav con F5 y XTTS.
  - -Cpu / -Cuda: fuerza la variante de PyTorch.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Smoke
#>
param(
    [switch]$Smoke,
    [switch]$Recreate,
    [switch]$Cpu,
    [switch]$Cuda
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if ($Recreate -and (Test-Path -LiteralPath ".venv")) {
    Write-Host "Recreando .venv ..."
    Remove-Item -LiteralPath ".venv" -Recurse -Force
}

$env:PODCAST_TTS_NONINTERACTIVE = "1"
if (-not $env:PODCAST_TTS_DOWNLOAD_MODELS) { $env:PODCAST_TTS_DOWNLOAD_MODELS = $(if ($Smoke) { "1" } else { "0" }) }
if (-not $env:PODCAST_TTS_INSTALL_SKILL) { $env:PODCAST_TTS_INSTALL_SKILL = "0" }
$installArgs = @("/y")
if ($Cpu) { $installArgs += "/cpu" }
if ($Cuda) { $installArgs += "/cuda" }

# Ruta relativa (ya estamos en $Root): cmd /c rompe las rutas absolutas con "&" o "(".
& cmd.exe /d /c "bats\install.bat" @installArgs
if ($LASTEXITCODE -ne 0) { throw "bats\install.bat fallo (codigo $LASTEXITCODE)" }

if ($Smoke) {
    $env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:COQUI_TOS_AGREED = "1"
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    Write-Host "`nSmoke test F5-TTS ..."
    & $py -W ignore scripts\smoke_f5.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_f5.py fallo" }
    Write-Host "`nSmoke test XTTS v2 ..."
    & $py -W ignore scripts\smoke_xtts.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_xtts.py fallo" }
}
