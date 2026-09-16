@echo off
REM ---------------------------------------------------------------------------
REM Build and run the self test for BLUI's Windows OLE drop source.
REM
REM The drop source depends on nothing but the Windows SDK, so it can be
REM compiled on its own - no CMake, no GHOST build, no window. That makes it
REM possible to check the CF_HDROP payload and the COM contract quickly.
REM
REM The last part is deliberately split across processes. Whether clipboard data
REM survives the process that published it decides whether the OLE publish path
REM in GHOST_DragSourceWin32_ClipboardSetFiles is load-bearing, and that is not
REM a question to settle by recollection of what the API promises. One process
REM sets and exits; a second, by then the only one alive, reads. Both transports
REM are measured so the answer is a comparison and not a single data point.
REM
REM   build_dragsource_selftest.cmd
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
   /I intern\ghost /I intern\ghost\intern ^
   blui\tools\dragsource_selftest.cc intern\ghost\intern\GHOST_DragSourceWin32.cc ^
   /Fe:"%OUT%\dragsource_selftest.exe" ^
   /Fo:"%OUT%\\" ^
   /link ole32.lib shell32.lib user32.lib
if %ERRORLEVEL% NEQ 0 (
  popd
  echo ERROR: compilation failed.
  exit /b 1
)
popd

echo.
"%OUT%\dragsource_selftest.exe"
set "RC=%ERRORLEVEL%"

echo.
echo clipboard lifetime across processes:
"%OUT%\dragsource_selftest.exe" --set
"%OUT%\dragsource_selftest.exe" --check
if %ERRORLEVEL% NEQ 0 set "RC=1"

echo.
echo for comparison, the transport this replaced:
"%OUT%\dragsource_selftest.exe" --set-raw
"%OUT%\dragsource_selftest.exe" --check

exit /b %RC%
