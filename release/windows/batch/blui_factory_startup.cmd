@echo off
echo Starting BLUI with factory settings, log files will be created
echo in your temp folder, windows explorer will open after you close BLUI
echo to help you find them.
echo.
echo Factory settings ignore your BLUI configuration, which is useful to tell
echo whether a problem comes from your preferences or from BLUI itself.
echo.
pause
mkdir "%temp%\BLUI\debug_logs" > NUL 2>&1
echo.
echo Starting BLUI and waiting for it to exit....
"%~dp0\BLUI" --factory-startup --python-expr "import bpy; bpy.ops.wm.sysinfo(filepath=r'%temp%\BLUI\debug_logs\BLUI_system_info.txt')" > "%temp%\BLUI\debug_logs\BLUI_debug_output.txt" 2>&1
explorer "%temp%\BLUI\debug_logs"
