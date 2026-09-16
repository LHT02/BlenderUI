@echo off
REM ---------------------------------------------------------------------------
REM BLUI build driver. This is the canonical copy and lives inside the source
REM repository, so a fresh clone can build without any extra files.
REM
REM   build.cmd            configure (only if needed) and build
REM   build.cmd configure  re-run CMake (keeps the cache), then build
REM   build.cmd nobuild    configure only
REM   build.cmd clean      delete the build directory (full rebuild after)
REM
REM The build tree is created next to the repository, i.e. <repo>\..\build,
REM matching Blender's out-of-source convention.
REM ---------------------------------------------------------------------------
setlocal

REM %~dp0 is <repo>\blui\ , so the repository root is one level up.
for %%I in ("%~dp0..") do set "SRC=%%~fI"
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
set "BUILD=%ROOT%\build"
set "CONFIG=%SRC%\build_files\cmake\config\blui.cmake"

if /I "%~1"=="clean" (
  if exist "%BUILD%" rmdir /s /q "%BUILD%"
  echo Removed "%BUILD%"
  exit /b 0
)

if not exist "%SRC%\CMakeLists.txt" (
  echo ERROR: BLUI source tree not found at "%SRC%".
  exit /b 1
)

REM --- locate the MSVC toolchain -------------------------------------------
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
set "VCVARS=%VSDIR%\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo ERROR: vcvars64.bat not found at "%VCVARS%".
  exit /b 1
)

if "%VSCMD_VER%"=="" (
  call "%VCVARS%" >nul
  if %ERRORLEVEL% NEQ 0 (
    echo ERROR: failed to initialise the MSVC environment.
    exit /b 1
  )
)

if not exist "%BUILD%" mkdir "%BUILD%"

set "MUST_CONFIGURE="
if not exist "%BUILD%\build.ninja" set "MUST_CONFIGURE=1"
if /I "%~1"=="configure" set "MUST_CONFIGURE=1"

if defined MUST_CONFIGURE (
  echo === Configuring BLUI ===
  cmake -G Ninja ^
    -C "%CONFIG%" ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_INSTALL_PREFIX="%BUILD%/bin" ^
    -S "%SRC%" ^
    -B "%BUILD%"
  if %ERRORLEVEL% NEQ 0 (
    echo ERROR: CMake configuration failed.
    exit /b 1
  )
)

if /I "%~1"=="nobuild" (
  echo Configuration complete.
  exit /b 0
)

echo === Building BLUI ===
REM `install` rather than plain `all`: Blender assembles the runnable layout
REM (scripts/, datafiles/, python/ under the version directory) with install
REM rules, so the executable is not usable on its own.
ninja -C "%BUILD%" install
if %ERRORLEVEL% NEQ 0 (
  echo ERROR: build failed.
  exit /b 1
)

echo.
echo === Build finished ===
if exist "%BUILD%\bin\BLUI.exe" echo Binary: %BUILD%\bin\BLUI.exe
exit /b 0
