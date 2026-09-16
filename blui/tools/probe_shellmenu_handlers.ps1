# SPDX-License-Identifier: GPL-2.0-or-later
<#
Which shell extension hangs the context menu?

BLUI's shell menu hangs inside QueryContextMenu, and that one call runs every
handler registered for the item. Nothing in it says which one failed to return,
so this runs them one at a time - each in its own process, with a timeout - and
prints which handler never came back.

    probe_shellmenu_handlers.ps1 -Path C:\Users\me\Documents\SomeFolder
    probe_shellmenu_handlers.ps1 -Path <path> -TimeoutSeconds 10

A handler that reports "not for this type" is normal: most CLSIDs are registered
for other kinds of item and answer E_FAIL from CoCreateInstance.
#>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Continue"

$tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Split-Path -Parent (Split-Path -Parent $tools)
$root = Split-Path -Parent $src
$probe = Join-Path $root "build\shellmenu_handler_probe.exe"

if (-not (Test-Path $probe)) {
  Write-Host "ERROR: $probe not found - run tools\build_shellmenu_handler_probe.cmd first"
  exit 1
}
if (-not (Test-Path $Path)) {
  Write-Host "ERROR: $Path does not exist"
  exit 1
}

$lists = @(
  "HKLM:\SOFTWARE\Classes\Directory\shellex\ContextMenuHandlers",
  "HKLM:\SOFTWARE\Classes\Folder\shellex\ContextMenuHandlers",
  "HKLM:\SOFTWARE\Classes\*\shellex\ContextMenuHandlers",
  "HKLM:\SOFTWARE\Classes\AllFilesystemObjects\shellex\ContextMenuHandlers"
)

$handlers = @{}
foreach ($list in $lists) {
  if (-not (Test-Path $list)) { continue }
  Get-ChildItem $list -ErrorAction SilentlyContinue | ForEach-Object {
    $clsid = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'(default)'
    if ($clsid -and $clsid -match '^\{') {
      $dll = (Get-ItemProperty "HKLM:\SOFTWARE\Classes\CLSID\$clsid\InprocServer32" -ErrorAction SilentlyContinue).'(default)'
      if (-not $handlers.ContainsKey($clsid)) {
        $handlers[$clsid] = [pscustomobject]@{
          Name  = $_.PSChildName
          Clsid = $clsid
          Dll   = $dll
        }
      }
    }
  }
}

Write-Host ("Handlers registered for {0}:" -f $Path)
Write-Host ("{0} distinct CLSID(s)`n" -f $handlers.Count)

$hung = @()
$ok = @()
foreach ($h in $handlers.Values | Sort-Object Name) {
  $out = Join-Path $env:TEMP ("blui_h_" + ($h.Clsid -replace '[{}]', '') + ".txt")
  Remove-Item $out -ErrorAction SilentlyContinue

  Write-Host ("  {0,-24} {1}" -f $h.Name, $h.Clsid) -NoNewline
  $p = Start-Process -FilePath $probe -ArgumentList @($Path, $h.Clsid) -PassThru -NoNewWindow `
                     -RedirectStandardOutput $out -RedirectStandardError "$out.err"
  $exited = $p.WaitForExit($TimeoutSeconds * 1000)

  if (-not $exited) {
    & taskkill /T /F /PID $p.Id 2>&1 | Out-Null
    Write-Host "  <<< HUNG (no return in ${TimeoutSeconds}s)"
    $hung += $h
    continue
  }

  $text = (Get-Content $out -Raw -ErrorAction SilentlyContinue)
  $timing = ($text -split "`n" | Where-Object { $_ -match 'QueryContextMenu\s+(\d+) ms' })
  if ($p.ExitCode -eq 2) {
    Write-Host "  not for this type"
  }
  elseif ($timing) {
    Write-Host ("  {0}" -f $timing.Trim())
    $ok += $h
  }
  else {
    Write-Host ("  exit {0} (no timing)" -f $p.ExitCode)
  }
}

Write-Host ""
if ($hung.Count -eq 0) {
  Write-Host "RESULT none of the registered handlers hung on their own"
  Write-Host "NOTE   the hang may need them loaded together, or come from a handler"
  Write-Host "       registered somewhere this list does not cover"
  exit 0
}

Write-Host "RESULT hung:"
foreach ($h in $hung) {
  Write-Host ("  {0}  {1}`n      {2}" -f $h.Name, $h.Clsid, $h.Dll)
}
exit 1
