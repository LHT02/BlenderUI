@echo off
echo Starting BLUI with debug logging options, log files will be created
echo in your temp folder, windows explorer will open after you close BLUI
echo to help you find them.
echo.
echo If you report a bug you can attach these files by dragging them into the
echo text area of your report, please include both BLUI_debug_output.txt and
echo BLUI_system_info.txt in your report.
echo.
pause
mkdir "%temp%\BLUI\debug_logs" > NUL 2>&1
echo.
echo Starting BLUI and waiting for it to exit....
set PYTHONPATH=
"%~dp0\BLUI" --debug --python-expr "import bpy; bpy.ops.wm.sysinfo(filepath=r'%temp%\BLUI\debug_logs\BLUI_system_info.txt')" > "%temp%\BLUI\debug_logs\BLUI_debug_output.txt" 2>&1 < %0
explorer "%temp%\BLUI\debug_logs"
