@echo off
REM ---------------------------------------------------------------------------
REM Paste files from the system clipboard, end to end.
REM
REM This one needs a launcher rather than an invocation because the clipboard
REM has to be filled from outside BLUI: a copy needs a file selected, and the
REM file browser's list cannot be driven from a script. Windows Forms is used
REM because Set-Clipboard -Path is not available in every PowerShell.
REM
REM   check_clipboard_paste.cmd
REM ---------------------------------------------------------------------------
setlocal

for %%I in ("%~dp0..\..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
set "EXE=%ROOT%\build\bin\BLUI.exe"

set "PSRC=%TEMP%\blui_paste_src"
set "PDST=%TEMP%\blui_paste_dst"
set "PNAME=pasted.txt"

if not exist "%EXE%" (
  echo ERROR: %EXE% not found - build first.
  exit /b 1
)

rmdir /s /q "%PSRC%" 2>nul
rmdir /s /q "%PDST%" 2>nul
mkdir "%PSRC%" 2>nul
mkdir "%PDST%" 2>nul
echo paste probe payload > "%PSRC%\%PNAME%"

REM Setting the clipboard is not enough - it can fail silently, and OLE data that
REM was never flushed dies with the process that set it. set_clipboard_files.ps1
REM sets it with copy:true, reads it back and retries, so a failure here is the
REM harness saying so rather than BLUI looking broken three steps later.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0set_clipboard_files.ps1" -PathList "%PSRC%\%PNAME%"
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: could not put a file list on the clipboard.
  exit /b 1
)

set "BLUI_PASTE_DST=%PDST%"
set "BLUI_PASTE_NAME=%PNAME%"

pushd "%SRC%"
"%EXE%" --factory-startup --python blui\tools\check_clipboard_paste.py
set "RC=%ERRORLEVEL%"
popd

rmdir /s /q "%PSRC%" 2>nul
rmdir /s /q "%PDST%" 2>nul
exit /b %RC%
