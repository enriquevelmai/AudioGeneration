<#
.SYNOPSIS
  Compatibility: installation lives in bats\install.bat. This script just calls it.

.DESCRIPTION
  Runs bats\install.bat in non-interactive mode (detects an NVIDIA GPU, uv sync with
  the local + cuda|cpu + desktop extras, check_env). It does not download models or install
  the skill unless asked to.
  - -Recreate: deletes .venv before installing.
  - -Smoke: also downloads the models and generates output\smoke_*.wav with F5 and XTTS.
  - -Cpu / -Cuda: forces the PyTorch variant.

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
    Write-Host "Recreating .venv ..."
    Remove-Item -LiteralPath ".venv" -Recurse -Force
}

$env:PODCAST_TTS_NONINTERACTIVE = "1"
if (-not $env:PODCAST_TTS_DOWNLOAD_MODELS) { $env:PODCAST_TTS_DOWNLOAD_MODELS = $(if ($Smoke) { "1" } else { "0" }) }
if (-not $env:PODCAST_TTS_INSTALL_SKILL) { $env:PODCAST_TTS_INSTALL_SKILL = "0" }
$installArgs = @("/y")
if ($Cpu) { $installArgs += "/cpu" }
if ($Cuda) { $installArgs += "/cuda" }

# Relative path (we are already in $Root): cmd /c breaks absolute paths containing "&" or "(".
& cmd.exe /d /c "bats\install.bat" @installArgs
if ($LASTEXITCODE -ne 0) { throw "bats\install.bat failed (exit code $LASTEXITCODE)" }

if ($Smoke) {
    $env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:COQUI_TOS_AGREED = "1"
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    Write-Host "`nSmoke test F5-TTS ..."
    & $py -W ignore scripts\smoke_f5.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_f5.py failed" }
    Write-Host "`nSmoke test XTTS v2 ..."
    & $py -W ignore scripts\smoke_xtts.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_xtts.py failed" }
}
