@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
for /f "tokens=1,2,3 delims=|" %%A in ('python -c "from augment.config import load_config; cfg = load_config(); print(f'{cfg.server.host}|{cfg.server.port}|http://127.0.0.1:{cfg.server.port}/')" 2^>nul') do (
  set AUGMENT_RUNTIME_HOST=%%A
  set AUGMENT_RUNTIME_PORT=%%B
  set AUGMENT_LOCAL_URL=%%C
)
if not defined AUGMENT_RUNTIME_HOST set AUGMENT_RUNTIME_HOST=127.0.0.1
if not defined AUGMENT_RUNTIME_PORT set AUGMENT_RUNTIME_PORT=8787
if not defined AUGMENT_LOCAL_URL set AUGMENT_LOCAL_URL=http://127.0.0.1:8787/
echo Starting Augment at %AUGMENT_LOCAL_URL% ^(bind %AUGMENT_RUNTIME_HOST%:%AUGMENT_RUNTIME_PORT% ^)
start "Augment Browser" /min cmd /c "timeout /t 3 /nobreak >nul && start %AUGMENT_LOCAL_URL% && exit"
python -m augment.cli serve --host %AUGMENT_RUNTIME_HOST% --port %AUGMENT_RUNTIME_PORT%
if errorlevel 1 (
  echo.
  echo ----------------------------------------
  echo   Error: Augment server failed to start.
  echo   Install dependencies with:
  echo   python -m pip install -e .[dev]
  echo ----------------------------------------
  pause
)
endlocal
