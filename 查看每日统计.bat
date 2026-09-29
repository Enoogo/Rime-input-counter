@echo off
rem Generate and open the Rime daily input chart (RimeData folder).
setlocal
cd /d "%~dp0"
set "GEN=0"

set "RUN="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "RUN=py -3"
)
if defined RUN goto :gen
where python >nul 2>nul
if not errorlevel 1 (
    python --version >nul 2>nul
    if not errorlevel 1 set "RUN=python"
)
if defined RUN goto :gen
echo [INFO] Python 3 not found - using the built-in PowerShell chart generator.
goto :psgen

:gen
echo Running: %RUN% plot_input_count.py
%RUN% plot_input_count.py
if not errorlevel 1 set "GEN=1"
if "%GEN%"=="1" goto :open
echo [WARN] Python chart failed - trying the PowerShell fallback ...

:psgen
echo Running PowerShell chart generator ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0chart_powershell.ps1"
if errorlevel 1 (
    echo [ERROR] Chart generation failed.
    pause
    exit /b 1
)

:open
if exist "%~dp0input_count_chart.html" (
    start "" "%~dp0input_count_chart.html"
) else (
    echo [ERROR] Output file not found: input_count_chart.html
    pause
    exit /b 1
)
exit /b 0
