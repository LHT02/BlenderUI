# SPDX-License-Identifier: GPL-2.0-or-later
<#
Commit, but only if the verification suite passes.

This exists because that rule was broken. A commit went in with
`check_all: FAILED - 1 of 18` in the same output, because the commit command
was simply the next line in a script and nothing gated it. Discipline is not a
mechanism; this is.

    commit_if_green.ps1 -MessageFile build\commitmsg.txt
    commit_if_green.ps1 -MessageFile build\commitmsg.txt -SkipSuite   # for docs-only

Exits 1 without committing when the suite fails, and prints the failures.
#>
param(
  [Parameter(Mandatory = $true)][string]$MessageFile,
  [switch]$SkipSuite
)

$ErrorActionPreference = "Continue"

$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Split-Path -Parent (Split-Path -Parent $tools)
$root = Split-Path -Parent $src
$checkAll = Join-Path $tools "check_all.ps1"

if (-not (Test-Path $MessageFile)) {
  Write-Host "ERROR: $MessageFile not found"
  exit 1
}

Push-Location $root
try {
  if (-not $SkipSuite) {
    Write-Host "=== running the suite before committing ==="
    & pwsh -NoProfile -File $checkAll
    if ($LASTEXITCODE -ne 0) {
      Write-Host ""
      Write-Host "REFUSING TO COMMIT: check_all failed. Nothing was committed."
      Write-Host "The tree is unchanged - fix the failure, then run this again."
      exit 1
    }
  }

  Push-Location $src
  try {
    & git add -A
    & git commit -q -F $MessageFile
    if ($LASTEXITCODE -ne 0) {
      Write-Host "git commit failed."
      exit 1
    }
    & git log --oneline -1
    $dirty = & git status --porcelain
    if ($dirty) { Write-Host "note: still modified after the commit:"; $dirty }
  }
  finally { Pop-Location }
}
finally { Pop-Location }

exit 0
