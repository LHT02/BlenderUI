@echo off
REM ---------------------------------------------------------------------------
REM Build shellmenu_handler_probe.exe - one shell context-menu handler at a time.
REM
REM Depends on the Windows SDK only, like the other self tests, so it builds
REM without CMake and without GHOST.
REM
REM   build_shellmenu_handler_probe.cmd
REM ---------------------------------------------------------------------------
setlocal

for %%I in ("%~dp0..\..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..\..") do set "ROOT=%%~fI"
set "OUT=%ROOT%\build"

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo ERROR: vswhere.exe not found - Visual Studio 2022 is required.
  exit /b 1
)
set "VSDIR="
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDIR=%%i"
if not defined VSDIR (
  echo ERROR: no Visual Studio installation with the C++ toolset was found.
  exit /b 1
)

if "%VSCMD_VER%"=="" (
  call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul
  if %ERRORLEVEL% NEQ 0 exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"

pushd "%SRC%"
cl /nologo /EHsc /std:c++17 /utf-8 ^
   blui\tools\shellmenu_handler_probe.cc ^
   /Fe:"%OUT%\shellmenu_handler_probe.exe" ^
   /Fo:"%OUT%\\" ^
   /link ole32.lib shell32.lib shlwapi.lib user32.lib
if %ERRORLEVEL% NEQ 0 (
  popd
  echo ERROR: compilation failed.
  exit /b 1
)
popd

echo.
echo built "%OUT%\shellmenu_handler_probe.exe"
exit /b 0
