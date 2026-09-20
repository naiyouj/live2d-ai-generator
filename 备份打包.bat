@echo off
cd /d "%~dp0"
title L2D - Backup

echo ============================================================
echo   Project backup (API key is EXCLUDED automatically)
echo   Add --no-venv for a much smaller archive.
echo ============================================================
echo.

"%~dp0.venv\Scripts\python.exe" "tools\make_backup.py" %*
set RC=%errorlevel%

echo.
if not errorlevel 1 (
  echo   Backup finished.
) else (
  echo   Backup FAILED with code %RC%.
)
pause
