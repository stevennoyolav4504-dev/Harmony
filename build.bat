@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Harmony - Build desktop application
"%~dp0venv\Scripts\python.exe" -m PyInstaller --noconfirm Harmony.spec
if errorlevel 1 exit /b 1
if exist "browsers" (
    robocopy "browsers" "dist\Harmony\_internal\browsers" /E /NFL /NDL /NJH /NJS
    if errorlevel 8 exit /b 1
)
if exist "runtime\node" (
    robocopy "runtime\node" "dist\Harmony\runtime\node" /E /NFL /NDL /NJH /NJS
    if errorlevel 8 exit /b 1
)
copy /y "icon.ico" "dist\Harmony\icon.ico" >nul
echo Build complete: dist\Harmony\Harmony.exe
