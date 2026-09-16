@echo off
REM ---------------------------------------------------------------------------
REM Convenience forwarder to the suite runner, so it can be started from a cmd
REM prompt or a build script without remembering the .ps1 extension.
REM
REM The real runner is check_all.ps1 next to this file - it needs
REM `WaitForExit(ms)` and `taskkill /T` to bound a check that hangs, which cmd
REM cannot do. See the comment at the top of that file for why a timeout and a
REM SKIP check are both load-bearing.
REM
REM   check_all.cmd            the whole suite
REM   check_all.cmd <name>     only checks whose name contains <name>
REM ---------------------------------------------------------------------------
pwsh -NoProfile -File "%~dp0check_all.ps1" %*
exit /b %ERRORLEVEL%
