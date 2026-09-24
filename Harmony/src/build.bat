@echo off
rem Build script lives in <project root>\src; project root is its parent directory.
set "ROOT=%~dp0.."
echo Harmony - Build desktop application
"%ROOT%\venv\Scripts\python.exe" "%~dp0tools\build_brand_assets.py"
if errorlevel 1 exit /b 1
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
