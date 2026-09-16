# SPDX-License-Identifier: GPL-2.0-or-later
#
# The window title follows the content, and does not carry the product name.
#
#     pwsh -NoProfile -File blui/tools/check_window_title.ps1
#
# Written in PowerShell rather than as a BLUI-side check because the property
# being tested is the operating system's idea of the window title, which nothing
# inside BLUI can read back. It is the same value a user sees in the taskbar.
#
# Both halves are requirements, not preferences: the title has to name what the
# window is showing (the directory, in the file browser) and it must NOT repeat
# the product name, which is what it did before wm_window_title() was changed -
# every window read "BLUI" whatever it held.

$ErrorActionPreference = 'Stop'

# This file is at <root>\source\blui\tools\, so three steps up is the root.
$root = $PSScriptRoot
for ($i = 0; $i -lt 3; $i++) { $root = Split-Path $root -Parent }
$exe = Join-Path $root 'build\bin\BLUI.exe'

$failures = 0
function Report($ok, $message) {
    if ($ok) { Write-Host "  PASS  $message" } else { Write-Host "  FAIL  $message"; $script:failures++ }
}

Write-Host 'BLUI window title'

if (-not (Test-Path $exe)) {
    Write-Host "  FAIL  $exe not found - build first"
    exit 1
}

# Start from nothing, so the title read below belongs to the window this script
# opened rather than to one already there.
Get-Process BLUI -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Start-Process -FilePath $exe -ArgumentList '--factory-startup' | Out-Null

$process = $null
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
    $process = Get-Process BLUI -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -ne '' } | Select-Object -First 1
    if ($process) { break }
    Start-Sleep -Milliseconds 500
}

if (-not $process) {
    Report $false 'a BLUI window appeared with a title'
    exit 1
}

# Wait for the title to settle before reading it.
#
# GHOST creates the window with the product name as its title and
# wm_window_title() replaces it once there is a screen to describe. Breaking out
# of the wait above the moment a title exists therefore reads the creation title,
# which is "BLUI" - and reporting that as a defect sends you looking for a bug
# that is not there, which is exactly what it did the first time this ran.
$title = $process.MainWindowTitle
$settle = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $settle) {
    $process.Refresh()
    $title = $process.MainWindowTitle
    if ($title -and $title -ne 'BLUI') { break }
    Start-Sleep -Milliseconds 250
}

Write-Host "  NOTE  title is '$title'"

Report ($title -notmatch 'BLUI') 'the title does not carry the product name'
Report ($title -match '\\') 'the title names a path, not just an application'

# The file browser starts in the user's documents, so the title should end in
# that directory rather than being any path at all.
$documents = [Environment]::GetFolderPath('MyDocuments')
Report ($title.TrimEnd('\') -like "*$($documents.TrimEnd('\'))*") `
    "the title names the directory being shown ($documents)"

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue

Write-Host ''
if ($failures -eq 0) { Write-Host 'check_window_title: PASS'; exit 0 }
Write-Host "check_window_title: FAILED ($failures)"; exit 1
