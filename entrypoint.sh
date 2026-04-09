#!/bin/bash
# Guildclaw: OpenClaw + llama-server (GGUF) + Model Hub (:8080).
set -e
source /opt/openclaw/entrypoint-common.sh

echo "============================================"
echo "  Guildclaw — OpenClaw + llama.cpp (GGUF)"
echo "============================================"

LLAMA_API_KEY="${LLAMA_API_KEY:-${VLLM_API_KEY:-changeme}}"
OPENCLAW_WEB_PASSWORD="${OPENCLAW_WEB_PASSWORD:-${A2GO_AUTH_TOKEN:-changeme}}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
HF_HOME="${HF_HOME:-/workspace/huggingface}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-local-gguf}"
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-8192}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-99}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"

STATE_DIR=/workspace/.guildclaw
ACTIVE_FILE="$STATE_DIR/active.json"
LLAMA_PID_FILE=/tmp/guildclaw-llama.pid
GGUF_DIR=/workspace/models/gguf

export OPENCLAW_WEB_PASSWORD HF_HOME OPENCLAW_STATE_DIR LLAMA_API_KEY SERVED_MODEL_NAME LLAMA_CTX_SIZE LLAMA_N_GPU_LAYERS

# ggml-org: libmtmd.so и др. лежат в /app; без этого — «error while loading shared libraries: libmtmd.so.0»
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-/app/llama-server}"
if [ -d /app/lib ]; then
    export LD_LIBRARY_PATH="/app/lib:/app${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
elif [ -d /app ]; then
    export LD_LIBRARY_PATH="/app${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

oc_create_path_symlinks

BOT_CMD="openclaw"

mkdir -p "$HF_HOME" "$OPENCLAW_STATE_DIR" "$OPENCLAW_STATE_DIR/agents/main/sessions" \
    "$OPENCLAW_STATE_DIR/credentials" /workspace/openclaw "$STATE_DIR" "$GGUF_DIR"
chmod 700 "$OPENCLAW_STATE_DIR" "$OPENCLAW_STATE_DIR/agents" "$OPENCLAW_STATE_DIR/agents/main" \
    "$OPENCLAW_STATE_DIR/agents/main/sessions" "$OPENCLAW_STATE_DIR/credentials" 2>/dev/null || true

if [ ! -f "$OPENCLAW_STATE_DIR/openclaw.json" ]; then
    echo "Creating OpenClaw configuration (local-llama / llama.cpp)..."

    if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
        TELEGRAM_CONFIG="\"telegram\": { \"enabled\": true, \"botToken\": \"${TELEGRAM_BOT_TOKEN}\" }"
    else
        TELEGRAM_CONFIG="\"telegram\": { \"enabled\": true }"
    fi

    cat > "$OPENCLAW_STATE_DIR/openclaw.json" << EOF
{
  "agents": {
    "defaults": {
      "model": { "primary": "local-llama/${SERVED_MODEL_NAME}" },
      "workspace": "/workspace/openclaw"
    }
  },
  "models": {
    "providers": {
      "local-llama": {
        "baseUrl": "http://localhost:8000/v1",
        "apiKey": "${LLAMA_API_KEY}",
        "api": "openai-completions",
        "models": [{
          "id": "${SERVED_MODEL_NAME}",
          "name": "Local GGUF (llama.cpp)",
          "contextWindow": ${LLAMA_CTX_SIZE},
          "maxTokens": 4096,
          "reasoning": false,
          "input": ["text"],
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }]
      }
    }
  },
  "channels": {
    ${TELEGRAM_CONFIG}
  },
  "gateway": {
    "mode": "local",
    "bind": "lan",
    "auth": { "mode": "token", "token": "${OPENCLAW_WEB_PASSWORD}" }
  },
  "logging": { "level": "info" }
}
EOF
    chmod 600 "$OPENCLAW_STATE_DIR/openclaw.json"
    echo "Config created. Затем выберите GGUF в Model Hub (порт 8080) и нажмите «Активировать»."
else
    echo "Existing config found at $OPENCLAW_STATE_DIR/openclaw.json — preserving (синхронизируем id модели при необходимости)"
fi

python3 /opt/guildclaw/sync_openclaw_llama.py || true
oc_sync_gateway_auth "token"

echo "Starting Model Hub on :8080..."
cd /opt/guildclaw
python3 -m uvicorn model_hub.app:app --host 0.0.0.0 --port 8080 &
HUB_PID=$!

llama_supervisor() {
    set +e
    while true; do
        if [ -f "$ACTIVE_FILE" ]; then
            GGUF=$(jq -r .path "$ACTIVE_FILE" 2>/dev/null || echo "")
            SID=$(jq -r '.served_id // empty' "$ACTIVE_FILE" 2>/dev/null || echo "")
            [ -n "$SID" ] || SID="$SERVED_MODEL_NAME"
            if [ -n "$GGUF" ] && [ -f "$GGUF" ]; then
                echo "Starting llama-server: $GGUF (alias: $SID)"
                python3 /opt/guildclaw/sync_openclaw_llama.py || true
                # shellcheck disable=SC2086
                "$LLAMA_SERVER_BIN" \
                    -m "$GGUF" \
                    --host 0.0.0.0 \
                    --port 8000 \
                    --api-key "$LLAMA_API_KEY" \
                    -c "$LLAMA_CTX_SIZE" \
                    -ngl "$LLAMA_N_GPU_LAYERS" \
                    --jinja \
                    --alias "$SID" \
                    $LLAMA_SERVER_EXTRA_ARGS &
                echo $! > "$LLAMA_PID_FILE"
                wait "$(cat "$LLAMA_PID_FILE")"
                echo "llama-server exited (код $?), перезапуск через 2s..."
                sleep 2
            else
                echo "В active.json указан файл, которого нет на диске. Ждём..."
                sleep 6
            fi
        else
            echo "Нет активной модели. Откройте http://localhost:8080 (или :8080 на RunPod) и скачайте/активируйте .gguf"
            sleep 8
        fi
    done
}

llama_supervisor &
LLAMA_SUP_PID=$!

echo "Ожидание llama-server (если модель уже активирована)..."
MAX_WAIT=360
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "llama-server отвечает на /health"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done

python3 /opt/guildclaw/sync_openclaw_llama.py || true

echo ""
echo "Starting OpenClaw gateway..."
"$BOT_CMD" gateway --auth token --token "$OPENCLAW_WEB_PASSWORD" &
GATEWAY_PID=$!

echo ""
oc_print_ready "LLM API (llama.cpp)" "$SERVED_MODEL_NAME" "${LLAMA_CTX_SIZE} ctx" "token"
echo "  Model Hub: http://localhost:8080"
if [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "  Model Hub (RunPod proxy): https://${RUNPOD_POD_ID}-8080.proxy.runpod.net/"
fi
echo ""

cleanup() {
    kill "$HUB_PID" "$GATEWAY_PID" "$LLAMA_SUP_PID" 2>/dev/null || true
    if [ -f "$LLAMA_PID_FILE" ]; then
        kill "$(cat "$LLAMA_PID_FILE")" 2>/dev/null || true
    fi
}

trap 'cleanup; exit 0' SIGTERM SIGINT

wait "$GATEWAY_PID"
EXIT_CODE=$?
echo "OpenClaw gateway завершился (код $EXIT_CODE)"
cleanup
exit "$EXIT_CODE"
