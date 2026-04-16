@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not defined HUB_PORT set "HUB_PORT=8088"

echo.
echo === Guildclaw Model Hub ===
echo Folder: %CD%
echo Port:   %HUB_PORT%  (если задолбало совпадение со старым Hub — так и задумано; для 8080: set HUB_PORT=8080)
echo.

for %%P in (8080 %HUB_PORT%) do (
  echo Freeing port %%P...
  powershell -NoProfile -Command "& { $c = Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue; if ($c) { $c | ForEach-Object { Write-Host ('  kill PID ' + $_.OwningProcess); Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } } else { Write-Host '  (free)' } }"
)
timeout /t 1 /nobreak >nul

if not defined MODEL_GGUF_DIR (
  if defined GUILDCLAW_GGUF_DIR (set "MODEL_GGUF_DIR=%GUILDCLAW_GGUF_DIR%") else (set "MODEL_GGUF_DIR=%~dp0demo_workspace\models\gguf")
)
if not defined RUNTIME_STATE_DIR (
  if defined GUILDCLAW_STATE_DIR (set "RUNTIME_STATE_DIR=%GUILDCLAW_STATE_DIR%") else (set "RUNTIME_STATE_DIR=%~dp0demo_workspace\.guildclaw")
)
mkdir "%MODEL_GGUF_DIR%" 2>nul
mkdir "%RUNTIME_STATE_DIR%" 2>nul
set "PYTHONPATH=%~dp0"

where python 2>nul
python -c "import sys; print('Python:', sys.executable)" 2>nul
python -c "import model_hub.app as a; import model_hub.preset_downloader as p; print('app.py ->', a.__file__); print('UI module ->', p.__file__)" 2>nul
if errorlevel 1 (
  echo ERROR: cannot import model_hub. pip install -r model_hub\requirements.txt
  pause
  exit /b 1
)

echo.
echo Открой в браузере: http://127.0.0.1:%HUB_PORT%/
echo Вкладка браузера должна называться: Guildclaw Hub · preset+script
echo В DevTools - Network - ответ на GET / заголовок: X-Guildclaw-Hub-UI: preset-downloader
echo На странице вкладки: Пресеты с эмодзи СНАЧАЛА — 🎯  (если без эмодзи — это старый кэш/другой порт)
echo.
python -m uvicorn model_hub.app:app --host 127.0.0.1 --port %HUB_PORT% --reload
endlocal
