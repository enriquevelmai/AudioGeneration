# Crea los accesos directos "AudioGeneration" (Escritorio y menu Inicio) con WScript.Shell.
# Lo llama bats\create_shortcuts.bat; se puede usar suelto:
#   powershell -ExecutionPolicy Bypass -File scripts\create_shortcuts.ps1 [-Root <repo>] [-Dest <carpeta>]
# Con -Dest (pruebas) los accesos van a <Dest>\Escritorio y <Dest>\Menu Inicio en vez de
# a las carpetas reales del usuario.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Dest = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path $Root).Path

$exe = Join-Path $Root "AudioGeneration.exe"
$runBat = Join-Path $Root "bats\run.bat"
$icon = Join-Path $Root "assets\icon.ico"

if (Test-Path $exe) {
    $target = $exe; $arguments = ""; $style = 1
} elseif (Test-Path $runBat) {
    # Sin el exe, el acceso abre run.bat minimizado (run.bat lanza la app sin consola).
    $target = $runBat; $arguments = ""; $style = 7
} else {
    Write-Error "No se encuentra AudioGeneration.exe ni bats\run.bat en $Root"
    exit 1
}

if ($Dest) {
    $desktopDir = Join-Path $Dest "Escritorio"
    $startDir = Join-Path $Dest "Menu Inicio"
} else {
    $desktopDir = [Environment]::GetFolderPath("Desktop")          # respeta OneDrive
    $startDir = [Environment]::GetFolderPath("Programs")           # menu Inicio del usuario
}

$shell = New-Object -ComObject WScript.Shell
$made = 0
foreach ($dir in @($desktopDir, $startDir)) {
    if (-not $dir) { continue }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $lnkPath = Join-Path $dir "AudioGeneration.lnk"
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $target
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $Root
    $lnk.WindowStyle = $style
    $lnk.Description = "AudioGeneration - Podcast TTS Studio"
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    Write-Output "  Acceso creado: $lnkPath -> $target"
    $made++
}
if ($made -eq 0) { Write-Error "No se creo ningun acceso directo."; exit 1 }
exit 0
