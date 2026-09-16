@echo off
REM ---------------------------------------------------------------------------
REM Build and run the self test for BLUI's Windows OLE drop source.
REM
REM Like the shell menu host, the drop source depends on nothing but the Windows
REM SDK, so the whole payload and COM contract can be exercised without a
REM window, without GHOST and without CMake.
REM
REM The last part is deliberately split across processes. Clipboard data may or
REM may not survive the process that published it, and that single fact decides
REM whether the OLE publish path in GHOST_DragSourceWin32_ClipboardSetFiles is
REM load-bearing. One process sets and exits; a second, by then the only one
REM alive, reads. Both transports are measured so the answer does not rest on
REM anyone's recollection of what the API promises.
REM
REM   dragsource_selftest.cmd
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
   blui\tools\dragsource_selftest.cc intern\ghost\intern\GHOST_DragSourceWin32.cc ^
   /Fe:"%OUT%\dragsource_selftest.exe" ^
   /Fo:"%OUT%\\" ^
   /link ole32.lib shell32.lib user32.lib
if errorlevel 1 (
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
if errorlevel 1 (
  echo   ^-^> the OLE path does not survive process exit
  set "RC=1"
)

echo.
echo for comparison, the pre-OLE transport:
"%OUT%\dragsource_selftest.exe" --set-raw
"%OUT%\dragsource_selftest.exe" --check
if errorlevel 1 (
  echo   ^-^> plain SetClipboardData does not survive process exit either
)

exit /b %RC%
