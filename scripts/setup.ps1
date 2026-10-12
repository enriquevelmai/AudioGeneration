<#
.SYNOPSIS
  Instala (o repara) el entorno de podcast-tts desde cero. Idempotente.

.DESCRIPTION
  - Crea .venv con Python 3.11 (uv venv) si no existe.
  - Instala las dependencias exactas de uv.lock (uv sync), incluido torch 2.8.0+cu126.
  - Verifica CUDA y los imports de F5-TTS y XTTS (scripts/check_env.py).
  - Con -Smoke, ademas descarga los modelos (~3 GB la primera vez) y genera output/smoke_*.wav.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Smoke
#>
param(
    [switch]$Smoke,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Consola UTF-8: los nombres de speakers de XTTS llevan acentos (p.ej. "Camilla Holmstrom" con o umlaut)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:COQUI_TOS_AGREED = "1"

# --- uv ---
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $candidate = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $candidate) { $uv = $candidate }
}
if (-not $uv) {
    Write-Host "uv no encontrado. Instalalo con:  powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
    exit 1
}
Write-Host "uv: $uv"

# --- ffmpeg (pydub lo usa para mp3/mezcla) ---
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg no esta en PATH. Instalalo (p.ej. 'choco install ffmpeg') para que pydub pueda leer/escribir mp3."
}

# --- venv ---
$py = Join-Path $Root ".venv\Scripts\python.exe"
if ($Recreate -and (Test-Path ".venv")) {
    Write-Host "Recreando .venv ..."
    Remove-Item -Recurse -Force ".venv"
}
if (-not (Test-Path $py)) {
    Write-Host "Creando .venv con Python 3.11 ..."
    & $uv venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) { throw "uv venv fallo" }
}

# --- dependencias (lockfile) ---
Write-Host "Sincronizando dependencias con uv.lock (puede tardar: torch CUDA ~2.5 GB) ..."
if (Test-Path "uv.lock") {
    & $uv sync --extra dev --frozen
} else {
    & $uv sync --extra dev
}
if ($LASTEXITCODE -ne 0) { throw "uv sync fallo" }

# --- verificacion ---
& $py scripts\check_env.py
if ($LASTEXITCODE -ne 0) { throw "check_env.py detecto problemas" }

if ($Smoke) {
    Write-Host "`nSmoke test F5-TTS ..."
    & $py -W ignore scripts\smoke_f5.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_f5.py fallo" }
    Write-Host "`nSmoke test XTTS v2 ..."
    & $py -W ignore scripts\smoke_xtts.py
    if ($LASTEXITCODE -ne 0) { throw "smoke_xtts.py fallo" }
}

Write-Host "`nEntorno listo. Activa con:  .venv\Scripts\Activate.ps1"
