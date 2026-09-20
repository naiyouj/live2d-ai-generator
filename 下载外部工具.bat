@echo off
cd /d "%~dp0"
title L2D - Fetch External Tools

echo ============================================================
echo   Downloads the two external tool repos (see-through /
echo   image2live2d), applies local patches on top, and fetches
echo   the web preview JS libs. No git needed.
echo   Safe to re-run: finished downloads are skipped.
echo ============================================================
echo.

set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto run

rem venv missing (fresh machine): fall back to any system python
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.13 first, or
    echo run this script after setup: python -m venv .venv
    pause
    exit /b 1
)
set "PY=python"

:run
"%PY%" "%~dp0tools\fetch_tools.py"
set RC=%errorlevel%

echo.
echo ============================================================
if %RC%==0 (
  echo   DONE. If stage 3 ^(layering^) is needed, also run:
  echo     download_models bat   ~12 GB, one time
) else (
  echo   FAILED with code %RC% - re-run this script to retry.
)
echo ============================================================
pause
