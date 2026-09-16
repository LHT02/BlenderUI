@echo off
REM ---------------------------------------------------------------------------
REM Delete files, in a directory this check created.
REM
REM The first check to use `file.select_bookmark(dir=...)`, which is what makes
REM the file list drivable from a script at all. Deleting only ever happens
REM inside %TEMP%\blui_delete_probe, and the check asserts that the directory and
REM its subdirectory survive - so a mistake here is loud rather than destructive.
REM
REM   check_delete_files.cmd
REM ---------------------------------------------------------------------------
setlocal

for %%I in ("%~dp0..\..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
set "EXE=%ROOT%\build\bin\BLUI.exe"

set "DDIR=%TEMP%\blui_delete_probe"
set "KEEP=%DDIR%\keepme"

if not exist "%EXE%" (
  echo ERROR: %EXE% not found - build first.
  exit /b 1
)

rmdir /s /q "%DDIR%" 2>nul
mkdir "%DDIR%" 2>nul
mkdir "%KEEP%" 2>nul
echo one > "%DDIR%\one.txt"
echo two > "%DDIR%\two.txt"
echo keep > "%KEEP%\inner.txt"

set "BLUI_DELETE_DIR=%DDIR%"
set "BLUI_DELETE_FILES=one.txt,two.txt"
set "BLUI_DELETE_KEEPDIR=%KEEP%"

pushd "%SRC%"
"%EXE%" --factory-startup --python blui\tools\check_delete_files.py
set "RC=%ERRORLEVEL%"
popd

rmdir /s /q "%DDIR%" 2>nul
exit /b %RC%
