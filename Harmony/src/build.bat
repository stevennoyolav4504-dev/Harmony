@echo off
chcp 65001 >nul
rem 本脚本位于 <项目根>\src，项目根目录为其上一级
set "ROOT=%~dp0.."
echo Harmony - Build desktop application
"%ROOT%\venv\Scripts\python.exe" -m PyInstaller --noconfirm --distpath "%ROOT%\dist" --workpath "%ROOT%\build" "%~dp0Harmony.spec"
if errorlevel 1 exit /b 1
if exist "%ROOT%\browsers" (
    robocopy "%ROOT%\browsers" "%ROOT%\dist\Harmony\_internal\browsers" /E /NFL /NDL /NJH /NJS
    if errorlevel 8 exit /b 1
)
if exist "%ROOT%\runtime\node" (
    robocopy "%ROOT%\runtime\node" "%ROOT%\dist\Harmony\runtime\node" /E /NFL /NDL /NJH /NJS
    if errorlevel 8 exit /b 1
)
copy /y "%~dp0icon.ico" "%ROOT%\dist\Harmony\icon.ico" >nul
echo Build complete: dist\Harmony\Harmony.exe

