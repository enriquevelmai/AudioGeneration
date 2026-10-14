<#
.SYNOPSIS
  Installs (idempotently) the `podcast-tts` Claude Code skill by creating a junction
  %USERPROFILE%\.claude\skills\podcast-tts -> <repo>\skill\podcast-tts.

  Junctions do not require administrator rights. If a correct junction/symlink already
  exists it does nothing; if it points elsewhere it recreates it (unless -NoReplace); if it is a
  regular folder (old copy) it renames it to podcast-tts.bak-<date> before creating the junction.

  The skill wrappers (scripts/generate.ps1 and generate.sh) find the project by following
  the junction, so nothing else needs to be configured.

.PARAMETER Copy
  Copies the folder instead of creating a junction (you will have to run the script again after
  every change). Since a copy does not know where the project is, it also sets the user variable
  PODCAST_TTS_HOME to the repository root.

.PARAMETER NoReplace
  If a skill is already installed that points to ANOTHER project, it is left as is (non-interactive mode).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -Copy
#>
param([switch]$Copy, [switch]$NoReplace)
$ErrorActionPreference = 'Stop'

# -LiteralPath everywhere: with -Path, the [ ] in a path are treated as wildcards.
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Source = Join-Path $Root 'skill\podcast-tts'
$SkillsDir = Join-Path $env:USERPROFILE '.claude\skills'
$Target = Join-Path $SkillsDir 'podcast-tts'

if (-not (Test-Path -LiteralPath (Join-Path $Source 'SKILL.md'))) { throw "$Source\SKILL.md does not exist" }
[void][IO.Directory]::CreateDirectory($SkillsDir)

$item = Get-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue
if ($item) {
    $isLink = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    if ($isLink) {
        $current = @($item.Target)[0]
        $currentResolved = $null
        if ($current -and (Test-Path -LiteralPath $current)) {
            $currentResolved = (Resolve-Path -LiteralPath $current).Path.TrimEnd('\')
        }
        if (-not $Copy -and $currentResolved -eq $Source.TrimEnd('\')) {
            Write-Host "The skill is already installed: $Target -> $Source"
            exit 0
        }
        if ($NoReplace -and $currentResolved) {
            Write-Host "WARNING: a podcast-tts skill already points to '$current'; leaving it untouched (-NoReplace)."
            Write-Host "         To use this project: powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1"
            exit 0
        }
        Write-Host "The junction points to '$current'; recreating it."
        # Deletes only the link, not the contents of the target
        [IO.Directory]::Delete($Target)
    } else {
        $backup = "$Target.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Write-Host "A regular folder exists at $Target; renaming it to $backup"
        Rename-Item -LiteralPath $Target -NewName (Split-Path $backup -Leaf)
    }
}

if ($Copy) {
    Copy-Item -Recurse -LiteralPath $Source -Destination $Target
    [Environment]::SetEnvironmentVariable('PODCAST_TTS_HOME', $Root, 'User')
    $env:PODCAST_TTS_HOME = $Root
    Write-Host "Skill copied to $Target (run again with -Copy after every change)."
    Write-Host "User variable PODCAST_TTS_HOME = $Root (open a new console to see it)."
} else {
    # New-Item resolves -Target as a wildcard (the [ ] in the project path would fail), so it is
    # escaped. -Path, on the other hand, is used as is.
    $sourceEscaped = [Management.Automation.WildcardPattern]::Escape($Source)
    New-Item -ItemType Junction -Path $Target -Target $sourceEscaped | Out-Null
    Write-Host "Junction created: $Target -> $Source"
}

if (-not (Test-Path -LiteralPath (Join-Path $Target 'SKILL.md'))) { throw "Installation failed: cannot read $Target\SKILL.md" }
Write-Host 'OK: SKILL.md is accessible.'
