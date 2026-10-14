<#
.SYNOPSIS
  Compatibility wrapper: forwards all arguments to generate.ps1 (kept for older references).
#>
& (Join-Path $PSScriptRoot 'generate.ps1') @args
exit $LASTEXITCODE
