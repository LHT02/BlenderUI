# SPDX-License-Identifier: GPL-2.0-or-later
<#
Run the whole blui/tools verification suite and print one verdict.

The objective asks for the suite to be re-run after every stage. README.md
tells a person which script needs which flags, and that is exactly how it goes
wrong. Three separate traps, all of them seen here:

  - Four checks silently do nothing without a window. They print SKIP and still
    exit 0, so a bare exit code says "fine" for a check that never ran.
  - `check_save_isolation.py` needs a scratch path and exits 1 without one.
  - A check whose Python timer raises leaves BLUI sitting there with a window
    open and no work in flight. That is a hang, not a failure, and it burned 32
    minutes here because the first version of this runner passed only `%~2` and
    dropped `--enable-event-simulate`.

So this runner passes each check the flags its own docstring documents, treats a
SKIP as a failure, and kills any check that outlives its timeout.

    check_all.ps1              the whole suite
    check_all.ps1 <name>       only checks whose name contains <name>

Needs no MSVC environment; the two self tests set theirs up themselves.
#>
param([string]$Filter = "")

$ErrorActionPreference = "Continue"

$tools  = Split-Path -Parent $MyInvocation.MyCommand.Path
$src    = Split-Path -Parent (Split-Path -Parent $tools)
$root   = Split-Path -Parent $src
$bin    = Join-Path $root "build\bin\BLUI.exe"
$logDir = Join-Path $root "build\check_all"

if (-not (Test-Path $bin)) {
  Write-Host "ERROR: $bin not found - build first with build.cmd"
  exit 1
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Blui([string[]]$Extra) {
  # A check run through BLUI.exe. Every flag goes in as its own element - the
  # previous version of this runner formatted them positionally and silently
  # dropped one.
  return @{ Exe = $bin; Args = $Extra }
}

$checks = @(
  # --- head-less -----------------------------------------------------------
  @{ Name = "check_editor_set";        Timeout = 240; Cmd = (Blui @("--background", "--factory-startup", "--python", "$tools\check_editor_set.py")) }
  @{ Name = "check_preferences";       Timeout = 240; Cmd = (Blui @("--background", "--factory-startup", "--python", "$tools\check_preferences.py")) }
  @{ Name = "verify_startup";          Timeout = 240; Cmd = (Blui @("--background", "--factory-startup", "--python", "$tools\verify_startup.py")) }

  # --- need a real window; --background would make these SKIP ---------------
  @{ Name = "check_keymap_config";     Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\check_keymap_config.py")) }
  @{ Name = "check_component_window";  Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\check_component_window.py")) }
  @{ Name = "check_window_isolation";  Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\check_window_isolation.py")) }
  @{ Name = "check_window_new_without_window"; Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\check_window_new_without_window.py")) }
  @{ Name = "check_workspace_geometry"; Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\check_workspace_geometry.py")) }
  @{ Name = "check_save_isolation";    Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\check_save_isolation.py", "--", "$env:TEMP\blui_save_isolation_check.blend")) }
  @{ Name = "probe_document_isolation"; Timeout = 240; Cmd = (Blui @("--factory-startup", "--python", "$tools\probe_document_isolation.py")) }
  @{ Name = "check_file_ops";          Timeout = 240; Cmd = (Blui @("--factory-startup", "--enable-event-simulate", "--python", "$tools\probe_file_ops.py")) }

  # MUST run windowed: the freeze it guards against only happens on a GUI
  # thread, so under --background it would pass while the app still froze.
  # Side effect: it opens one Explorer window, because that is what the
  # operation under test does.
  @{ Name = "check_external_op";       Timeout = 120; Cmd = (Blui @("--factory-startup", "--python", "$tools\probe_external_op.py", "--", "C:\Windows", "FOLDER_OPEN")) }

  # --- drives synthetic input ----------------------------------------------
  @{ Name = "click_sweep";             Timeout = 300; Cmd = (Blui @("--debug", "--enable-event-simulate", "--python", "$tools\click_sweep.py")) }
  @{ Name = "check_menu_draw";         Timeout = 300; Cmd = (Blui @("--factory-startup", "--enable-event-simulate", "--python", "$tools\check_menu_draw.py")) }

  # --- self-contained ------------------------------------------------------
  @{ Name = "check_clipboard_paste";   Timeout = 300; Cmd = @{ Exe = "cmd.exe"; Args = @("/c", "$tools\check_clipboard_paste.cmd") } }
  @{ Name = "shellmenu_selftest";      Timeout = 600; Cmd = @{ Exe = "cmd.exe"; Args = @("/c", "$tools\build_shellmenu_selftest.cmd") } }
  @{ Name = "dragsource_selftest";     Timeout = 600; Cmd = @{ Exe = "cmd.exe"; Args = @("/c", "$tools\build_dragsource_selftest.cmd") } }
  @{ Name = "check_window_title";      Timeout = 240; Cmd = @{ Exe = "pwsh"; Args = @("-NoProfile", "-File", "$tools\check_window_title.ps1") } }
)

if ($Filter -ne "") {
  $checks = @($checks | Where-Object { $_.Name -like "*$Filter*" })
  if ($checks.Count -eq 0) {
    Write-Host "ERROR: no check matches '$Filter'"
    exit 1
  }
}

Write-Host "BLUI verification suite"
Write-Host ""

$total = 0
$failed = 0

foreach ($check in $checks) {
  $name = $check.Name
  $total++

  $stdout = Join-Path $logDir "$name.log"
  $stderr = Join-Path $logDir "$name.err"
  Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

  $exe = $check.Cmd.Exe
  $argList = $check.Cmd.Args

  # Printed before the run so that a hang shows which check is hanging - the
  # whole reason this needs a timeout at all.
  Write-Host ("  ....  {0}" -f $name) -NoNewline

  $proc = Start-Process -FilePath $exe -ArgumentList $argList -PassThru -NoNewWindow `
                        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $exited = $proc.WaitForExit($check.Timeout * 1000)

  $verdict = $null
  if (-not $exited) {
    # `/T` as well: the two self tests are cmd wrappers that spawn the compiler,
    # and killing only the wrapper would leave cl.exe behind.
    & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
    $verdict = "HANG"
  }
  else {
    $code = $proc.ExitCode
    $text = ""
    if (Test-Path $stdout) { $text += (Get-Content $stdout -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $stderr) { $text += (Get-Content $stderr -Raw -ErrorAction SilentlyContinue) }

    if ($code -ne 0) {
      $verdict = "FAIL"
    }
    elseif ($text -match "SKIP") {
      $verdict = "SKIP"
    }
    elseif ($text -match "Traceback \(most recent call last\)") {
      # A Python exception does not always fail the process. Inside a menu's
      # draw() it aborts the rest of the menu and the check still exits 0, so
      # a truncated menu reads as a pass - which is how a missing `CUT` icon
      # silently deleted every entry after it.
      $verdict = "TRACEBACK"
    }
  }

  if ($null -eq $verdict) {
    Write-Host ("`r  PASS  {0,-40}" -f $name)
  }
  else {
    Write-Host ("`r  {0,-5} {1,-40}" -f $verdict, $name)
    $failed++
  }
}

Write-Host ""
if ($failed -eq 0) {
  Write-Host "check_all: PASS - $total checks"
  exit 0
}
Write-Host "check_all: FAILED - $failed of $total"
exit 1
