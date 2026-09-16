@echo off
REM ---------------------------------------------------------------------------
REM Create a folder, in a directory this check created.
REM
REM Uses `file.select_bookmark(dir=...)` to put the browser somewhere known, the
REM same unlock check_delete_files uses. Everything happens inside
REM %TEMP%\blui_newfolder_probe; the check asserts the directory started empty
REM and that exactly one folder appeared.
REM
REM   check_new_folder.cmd
REM ---------------------------------------------------------------------------
setlocal

for %%I in ("%~dp0..\..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
set "EXE=%ROOT%\build\bin\BLUI.exe"

set "NDIR=%TEMP%\blui_newfolder_probe"

if not exist "%EXE%" (
  echo ERROR: %EXE% not found - build first.
  exit /b 1
)

rmdir /s /q "%NDIR%" 2>nul
mkdir "%NDIR%" 2>nul

set "BLUI_NEWFOLDER_DIR=%NDIR%"

pushd "%SRC%"
"%EXE%" --factory-startup --python blui\tools\check_new_folder.py
set "RC=%ERRORLEVEL%"
popd

rmdir /s /q "%NDIR%" 2>nul
exit /b %RC%
