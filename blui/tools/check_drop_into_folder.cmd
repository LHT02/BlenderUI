@echo off
REM ---------------------------------------------------------------------------
REM Drop a file into the file browser, from a different volume.
REM
REM GHOST's OLE drop target cannot be driven from a script, so this drives the
REM operator the dropbox calls. What it tests is the half that was missing: that
REM a dropped file is copied into the folder on screen rather than merely having
REM its path recorded.
REM
REM   check_drop_into_folder.cmd
REM ---------------------------------------------------------------------------
setlocal

for %%I in ("%~dp0..\..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
set "EXE=%ROOT%\build\bin\BLUI.exe"

set "DSRC=%ROOT%\build\drop_probe_src"
set "DDST=%TEMP%\blui_drop_dst"
set "DNAME=dropprobe.txt"

if not exist "%EXE%" (
  echo ERROR: %EXE% not found - build first.
  exit /b 1
)

rmdir /s /q "%DSRC%" 2>nul
rmdir /s /q "%DDST%" 2>nul
mkdir "%DSRC%" 2>nul
mkdir "%DDST%" 2>nul
echo drop probe payload > "%DSRC%\%DNAME%"

set "BLUI_DROP_SRC=%DSRC%\%DNAME%"
set "BLUI_DROP_DST=%DDST%"
set "BLUI_DROP_NAME=%DNAME%"

pushd "%SRC%"
"%EXE%" --factory-startup --python blui\tools\check_drop_into_folder.py
set "RC=%ERRORLEVEL%"
popd

rmdir /s /q "%DSRC%" 2>nul
rmdir /s /q "%DDST%" 2>nul
exit /b %RC%
