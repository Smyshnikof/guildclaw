#!/usr/bin/env bash
# Локально по умолчанию :8088, чтобы не цепляться за старый Hub на :8080
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export HUB_PORT="${HUB_PORT:-8088}"

echo ""
echo "=== Guildclaw Model Hub ==="
echo "Folder: $ROOT"
echo "Port:   $HUB_PORT"
echo ""

free_port() {
  local p="$1"
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "& { \$c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue; if (\$c) { \$c | ForEach-Object { Write-Host ('  kill PID ' + \$_.OwningProcess); Stop-Process -Id \$_.OwningProcess -Force -ErrorAction SilentlyContinue } } else { Write-Host '  (free)' } }" || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${p}/tcp" 2>/dev/null || true
  fi
}

for p in 8080 "$HUB_PORT"; do
  echo "Freeing port $p..."
  free_port "$p"
done
sleep 1

export GUILDCLAW_GGUF_DIR="${GUILDCLAW_GGUF_DIR:-$ROOT/demo_workspace/models/gguf}"
export GUILDCLAW_STATE_DIR="${GUILDCLAW_STATE_DIR:-$ROOT/demo_workspace/.guildclaw}"
mkdir -p "$GUILDCLAW_GGUF_DIR" "$GUILDCLAW_STATE_DIR"
export PYTHONPATH="$ROOT"

python -c "import sys; print('Python:', sys.executable)"
python -c "import model_hub.app as a, model_hub.preset_downloader as p; print('app.py ->', a.__file__); print('UI module ->', p.__file__)"

echo ""
echo "Open: http://127.0.0.1:${HUB_PORT}/"
echo "Tab title: Guildclaw Hub · preset+script"
echo ""
exec python -m uvicorn model_hub.app:app --host 127.0.0.1 --port "$HUB_PORT" --reload
