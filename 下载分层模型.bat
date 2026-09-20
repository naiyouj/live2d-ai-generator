@echo off
cd /d "%~dp0"
title L2D - Model Downloader

echo ============================================================
echo   Stage 3 (layering) model downloader
echo   Total about 12 GB, only needed once.
echo   Already-downloaded files are skipped, safe to re-run.
echo   Do NOT close this window.
echo ============================================================
echo.

"%~dp0.venv\Scripts\python.exe" "tools\download_models.py"
set RC=%errorlevel%

echo.
echo ============================================================
if not errorlevel 1 (
  echo   SUCCESS - all models ready.
) else (
  echo   FAILED with code %RC% - re-run this script to retry.
)
echo ============================================================
pause
