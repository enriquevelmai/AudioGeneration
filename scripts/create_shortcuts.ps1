# Creates the "AudioGeneration" shortcuts (Desktop and Start menu) with WScript.Shell.
# Called by bats\create_shortcuts.bat; it can also be used on its own:
#   powershell -ExecutionPolicy Bypass -File scripts\create_shortcuts.ps1 [-Root <repo>] [-Dest <folder>]
# With -Dest (testing) the shortcuts go to <Dest>\Desktop and <Dest>\Start Menu instead of
# the user's real folders.
# -LiteralPath is used everywhere: with -Path, the [ ] in a path are treated as wildcards.
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Dest = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath $Root).Path

$exe = Join-Path $Root "AudioGeneration.exe"
$runBat = Join-Path $Root "bats\run.bat"
$icon = Join-Path $Root "assets\icon.ico"

if (Test-Path -LiteralPath $exe -PathType Leaf) {
    $target = $exe; $arguments = ""; $style = 1
} elseif (Test-Path -LiteralPath $runBat -PathType Leaf) {
    # Without the exe, the shortcut opens run.bat minimized (run.bat launches the app without a console).
    $target = $runBat; $arguments = ""; $style = 7
} else {
    Write-Error "Neither AudioGeneration.exe nor bats\run.bat was found in $Root"
    exit 1
}

if ($Dest) {
    $desktopDir = Join-Path $Dest "Desktop"
    $startDir = Join-Path $Dest "Start Menu"
} else {
    $desktopDir = [Environment]::GetFolderPath("Desktop")          # honours OneDrive
    $startDir = [Environment]::GetFolderPath("Programs")           # user's Start menu
}

$shell = New-Object -ComObject WScript.Shell
$made = 0
foreach ($dir in @($desktopDir, $startDir)) {
    if (-not $dir) { continue }
    [void][IO.Directory]::CreateDirectory($dir)
    $lnkPath = Join-Path $dir "AudioGeneration.lnk"
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $target
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $Root
    $lnk.WindowStyle = $style
    $lnk.Description = "AudioGeneration - Podcast TTS Studio"
    if (Test-Path -LiteralPath $icon -PathType Leaf) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    Write-Output "  Shortcut created: $lnkPath -> $target"
    $made++
}
if ($made -eq 0) { Write-Error "No shortcut was created."; exit 1 }
exit 0
