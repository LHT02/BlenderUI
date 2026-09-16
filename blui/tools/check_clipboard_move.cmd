@echo off
REM ---------------------------------------------------------------------------
REM Cut and paste a file across volumes, end to end.
REM
REM `BLI_rename` cannot cross a filesystem boundary, so before the fallback this
REM did nothing and said nothing. The source is put on D: and the destination on
REM C: precisely so the rename path is the one that fails.
REM
REM   check_clipboard_move.cmd
REM ---------------------------------------------------------------------------
setlocal

for %%I in ("%~dp0..\..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
set "EXE=%ROOT%\build\bin\BLUI.exe"

REM Source on the build volume, destination under %TEMP%; they must differ.
set "MSRC=%ROOT%\build\move_probe_src"
set "PDST=%TEMP%\blui_move_dst"
set "PNAME=moveprobe.txt"
set "DNAME=moveprobe_dir"

if not exist "%EXE%" (
  echo ERROR: %EXE% not found - build first.
  exit /b 1
)

rmdir /s /q "%MSRC%" 2>nul
rmdir /s /q "%PDST%" 2>nul
mkdir "%MSRC%" 2>nul
mkdir "%PDST%" 2>nul
echo move probe payload > "%MSRC%\%PNAME%"
mkdir "%MSRC%\%DNAME%" 2>nul
echo inner payload > "%MSRC%\%DNAME%\inner.txt"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0set_clipboard_files.ps1" -PathList "%MSRC%\%PNAME%","%MSRC%\%DNAME%" -Move
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: could not put the file on the clipboard as a cut.
  exit /b 1
)

set "BLUI_PASTE_DST=%PDST%"
set "BLUI_PASTE_NAME=%PNAME%"
set "BLUI_MOVE_SRC=%MSRC%\%PNAME%"
set "BLUI_MOVE_DIR=%MSRC%\%DNAME%"

pushd "%SRC%"
"%EXE%" --factory-startup --python blui\tools\check_clipboard_move.py
set "RC=%ERRORLEVEL%"
popd

rmdir /s /q "%MSRC%" 2>nul
rmdir /s /q "%PDST%" 2>nul
exit /b %RC%
