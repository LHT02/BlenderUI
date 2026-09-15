@echo off
REM ---------------------------------------------------------------------------
REM Build and run the self test for BLUI's Windows shell context menu.
REM
REM The shell menu host depends on nothing but the Windows SDK, so it can be
REM compiled on its own - no CMake, no GHOST build, no window. That makes it
REM possible to check the whole COM path (parsing the paths, binding to the
REM common parent folder, GetUIObjectOf, QueryContextMenu) quickly.
REM
REM   build_shellmenu_selftest.cmd
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
  if errorlevel 1 exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"

pushd "%SRC%"
cl /nologo /EHsc /std:c++17 /utf-8 ^
   /I intern\ghost /I intern\ghost\intern ^
   blui\tools\shellmenu_selftest.cc intern\ghost\intern\GHOST_ShellMenuWin32.cc ^
   /Fe:"%OUT%\shellmenu_selftest.exe" ^
   /Fo:"%OUT%\\" ^
   /link ole32.lib shell32.lib shlwapi.lib user32.lib
if errorlevel 1 (
  popd
  echo ERROR: compilation failed.
  exit /b 1
)
popd

echo.
"%OUT%\shellmenu_selftest.exe"
exit /b %ERRORLEVEL%
