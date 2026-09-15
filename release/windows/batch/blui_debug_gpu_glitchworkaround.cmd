@echo off
echo Starting BLUI with GPU debugging and glitch workaround options, log files
echo will be created in your temp folder, windows explorer will open after you
echo close BLUI to help you find them.
echo.
echo If you report a bug you can attach these files by dragging them into the
echo text area of your report, please include both BLUI_debug_output.txt and
echo BLUI_system_info.txt in your report.
echo.
pause
mkdir "%temp%\BLUI\debug_logs" > NUL 2>&1
echo.
echo Starting BLUI and waiting for it to exit....
"%~dp0\BLUI" --debug --debug-gpu --debug-gpu-force-workarounds --python-expr "import bpy; bpy.ops.wm.sysinfo(filepath=r'%temp%\BLUI\debug_logs\BLUI_system_info.txt')" > "%temp%\BLUI\debug_logs\BLUI_debug_output.txt" 2>&1 < %0
explorer "%temp%\BLUI\debug_logs"
