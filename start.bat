@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m app.run_server %*
) else (
  uv run python -m app.run_server %*
)
if errorlevel 1 (
  echo.
  echo Server exited with an error.
  pause
)
