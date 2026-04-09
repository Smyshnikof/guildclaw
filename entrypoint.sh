#!/bin/bash
# Guildclaw: OpenClaw + llama-server (GGUF) + Model Hub (:8080).
set -e
source /opt/openclaw/entrypoint-common.sh

echo "============================================"
echo "  Guildclaw — OpenClaw + llama.cpp (GGUF)"
echo "============================================"

# В образе задан LLAMA_API_KEY=changeme — тогда ${LLAMA_API_KEY:-$VLLM} не подхватывает VLLM_API_KEY; явно мержим.
LLAMA_API_KEY="${LLAMA_API_KEY:-${VLLM_API_KEY:-changeme}}"
if [ "$LLAMA_API_KEY" = "changeme" ] && [ -n "${VLLM_API_KEY:-}" ] && [ "$VLLM_API_KEY" != "changeme" ]; then
    LLAMA_API_KEY="$VLLM_API_KEY"
fi
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
    echo "Config created. При первом запуске подтянется GGUF по умолчанию; сменить модель — Model Hub (:8080)."
else
    echo "Existing config found at $OPENCLAW_STATE_DIR/openclaw.json — preserving (синхронизируем id модели при необходимости)"
fi

# Первый запуск / нет валидной активной модели: скачать дефолтный GGUF и записать active.json (HF_TOKEN подхватится для приватных зеркал).
guildclaw_bootstrap_default_gguf() {
    [ "${GUILDCLAW_BOOTSTRAP_GGUF:-1}" = "0" ] && return 0
    local url="${GUILDCLAW_DEFAULT_GGUF_URL:-}"
    local name="${GUILDCLAW_DEFAULT_GGUF_FILENAME:-gemma-4-E4B-it-Q4_K_M.gguf}"
    [ -z "$url" ] && return 0

    if [ -f "$ACTIVE_FILE" ]; then
        local p
        p=$(jq -r '.path // empty' "$ACTIVE_FILE" 2>/dev/null || echo "")
        if [ -n "$p" ] && [ -f "$p" ]; then
            echo "Активная модель уже есть ($p), авто-скачивание GGUF пропущено."
            return 0
        fi
    fi

    mkdir -p "$GGUF_DIR"
    local dest="$GGUF_DIR/$name"

    if [ ! -f "$dest" ]; then
        echo "Скачивание GGUF по умолчанию (может занять несколько минут)..."
        echo "  URL: $url"
        local tmp="${dest}.part"
        rm -f "$tmp"
        set +e
        if [ -n "${HF_TOKEN:-}" ] && [[ "$url" == *"huggingface.co"* ]]; then
            curl -fL --connect-timeout 30 --retry 5 --retry-delay 10 \
                -H "Authorization: Bearer ${HF_TOKEN}" -o "$tmp" "$url"
        else
            curl -fL --connect-timeout 30 --retry 5 --retry-delay 10 -o "$tmp" "$url"
        fi
        local cr=$?
        set -e
        if [ "$cr" -ne 0 ] || [ ! -s "$tmp" ]; then
            rm -f "$tmp"
            echo "WARN: не удалось скачать дефолтный GGUF (curl exit $cr). Загрузите модель вручную в Model Hub (:8080)."
            return 0
        fi
        mv "$tmp" "$dest"
        echo "Сохранено: $dest"
    else
        echo "Файл по умолчанию уже на диске: $dest"
    fi

    jq -n --arg p "$dest" --arg sid "$SERVED_MODEL_NAME" '{path: $p, served_id: $sid}' > "$ACTIVE_FILE"
    echo "Автоактивация: $dest (served_id=$SERVED_MODEL_NAME)"
}

python3 /opt/guildclaw/sync_openclaw_llama.py || true
oc_sync_gateway_auth "token"

echo "Starting Model Hub on :8080..."
cd /opt/guildclaw
python3 -m uvicorn model_hub.app:app --host 0.0.0.0 --port 8080 &
HUB_PID=$!

echo "Starting Pairing dashboard on :8081..."
python3 -m uvicorn pairing_dashboard.app:app --host 0.0.0.0 --port 8081 &
PAIRING_DASH_PID=$!

JUPYTER_PID=""
if [ "${GUILDCLAW_JUPYTER:-1}" != "0" ]; then
    mkdir -p /workspace/logs
    JUPYTER_TOKEN="${GUILDCLAW_JUPYTER_TOKEN:-}"
    if [ -z "$JUPYTER_TOKEN" ] && [ -n "${ACCESS_PASSWORD:-}" ]; then
        JUPYTER_TOKEN="$ACCESS_PASSWORD"
    fi
    if [ -z "$JUPYTER_TOKEN" ]; then
        echo "WARN: JupyterLab стартует без токена. Задайте GUILDCLAW_JUPYTER_TOKEN или ACCESS_PASSWORD (как в шаблоне ComfyUI/RunPod)."
    else
        echo "Starting JupyterLab on :8888 (токен задан)..."
    fi
    cd /workspace
    # Как в ComfyUI RunPod: https://github.com/.../scripts/start.sh — allow_origin, terminado, /workspace
    nohup jupyter lab --allow-root \
        --no-browser \
        --port=8888 \
        --ip=0.0.0.0 \
        --FileContentsManager.delete_to_trash=False \
        --ContentsManager.allow_hidden=True \
        --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' \
        --ServerApp.token="${JUPYTER_TOKEN}" \
        --ServerApp.allow_origin='*' \
        --ServerApp.root_dir=/workspace \
        --ServerApp.preferred_dir=/workspace \
        >> /workspace/logs/jupyterlab.log 2>&1 &
    JUPYTER_PID=$!
    echo "JupyterLab PID=$JUPYTER_PID (лог: /workspace/logs/jupyterlab.log)"
fi

# Hub сразу, чтобы во время долгого curl на дефолтный GGUF можно было зайти в UI
guildclaw_bootstrap_default_gguf

python3 /opt/guildclaw/sync_openclaw_llama.py || true

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
oc_sync_control_ui_origins

echo ""
echo "Starting OpenClaw gateway..."
"$BOT_CMD" gateway --auth token --token "$OPENCLAW_WEB_PASSWORD" &
GATEWAY_PID=$!

echo ""
oc_print_ready "LLM API (llama.cpp)" "$SERVED_MODEL_NAME" "${LLAMA_CTX_SIZE} ctx" "token"
echo "  Model Hub: http://localhost:8080"
echo "  Pairing dashboard: http://localhost:8081"
if [ -n "${JUPYTER_PID:-}" ]; then
    echo "  JupyterLab: http://localhost:8888/lab"
    if [ -n "${JUPYTER_TOKEN:-}" ]; then
        echo "    Вход: добавьте к URL ?token=<GUILDCLAW_JUPYTER_TOKEN или ACCESS_PASSWORD>"
    fi
fi
if [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "  Model Hub (RunPod proxy): https://${RUNPOD_POD_ID}-8080.proxy.runpod.net/"
    echo "  Pairing (RunPod proxy): https://${RUNPOD_POD_ID}-8081.proxy.runpod.net/"
    if [ -n "${JUPYTER_PID:-}" ]; then
        echo "  JupyterLab (RunPod proxy): https://${RUNPOD_POD_ID}-8888.proxy.runpod.net/lab"
    fi
fi
echo ""

cleanup() {
    kill "$HUB_PID" "$PAIRING_DASH_PID" "$GATEWAY_PID" "$LLAMA_SUP_PID" 2>/dev/null || true
    if [ -n "${JUPYTER_PID:-}" ]; then
        kill "$JUPYTER_PID" 2>/dev/null || true
    fi
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
