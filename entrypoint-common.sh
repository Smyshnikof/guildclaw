#!/bin/bash
# Общие хелперы для OpenClaw в Docker (локально, RunPod и т.д.).

oc_init_web_ui() {
    local pod_id="${RUNPOD_POD_ID:-}"
    if [ -n "$pod_id" ]; then
        WEB_UI_BASE="https://${pod_id}-18789.proxy.runpod.net"
    else
        WEB_UI_BASE="https://<pod-id>-18789.proxy.runpod.net"
    fi

    WEB_UI_TOKEN="${OPENCLAW_WEB_PASSWORD:-${A2GO_AUTH_TOKEN:-changeme}}"
    WEB_UI_URL="${WEB_UI_BASE}/?token=${WEB_UI_TOKEN}"
}

oc_print_ready() {
    local api_label="$1"
    local model_label="$2"
    local context_label="$3"
    local auth_mode="$4"
    shift 4 || true

    oc_init_web_ui

    echo "================================================"
    echo "  Ready!"
    echo "  ${api_label}: http://localhost:8000"
    echo "  OpenClaw Gateway: ws://localhost:18789"

    if [ "$auth_mode" = "token" ]; then
        echo "  Web UI: ${WEB_UI_URL}"
        echo "  Web UI Token: ${WEB_UI_TOKEN}"
    else
        echo "  Web UI: ${WEB_UI_BASE}"
        echo "  Web UI Password: ${WEB_UI_TOKEN}"
    fi

    if [ -n "$model_label" ]; then
        echo "  Model: ${model_label}"
    fi
    if [ -n "$context_label" ]; then
        echo "  Context: ${context_label}"
    fi

    for extra in "$@"; do
        if [ -n "$extra" ]; then
            echo "  ${extra}"
        fi
    done

    echo "  Status: ready for requests"
    echo "================================================"
}

oc_sync_gateway_auth() {
    local mode="${1:-token}"
    local cfg="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}/openclaw.json"
    if [ ! -f "$cfg" ]; then
        return
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "WARNING: python3 not found; skipping gateway auth sync"
        return
    fi

    OPENCLAW_GATEWAY_AUTH_MODE="$mode" python3 - <<'PY'
import json
import os

cfg = os.path.join(os.environ.get("OPENCLAW_STATE_DIR", os.path.expanduser("~/.openclaw")), "openclaw.json")
mode = os.environ.get("OPENCLAW_GATEWAY_AUTH_MODE", "token")
token = os.environ.get("OPENCLAW_WEB_PASSWORD", os.environ.get("A2GO_AUTH_TOKEN", "changeme"))

with open(cfg, "r", encoding="utf-8") as f:
    data = json.load(f)

gw = data.setdefault("gateway", {})
auth = gw.setdefault("auth", {})
changed = False

if mode == "token":
    if auth.get("mode") != "token":
        auth["mode"] = "token"
        changed = True
    if auth.get("token") != token:
        auth["token"] = token
        changed = True
    remote = gw.setdefault("remote", {})
    if remote.get("token") != token:
        remote["token"] = token
        changed = True
elif mode == "password":
    if auth.get("mode") != "password":
        auth["mode"] = "password"
        changed = True
    if auth.get("password") != token:
        auth["password"] = token
        changed = True

if changed:
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
PY
    chmod 600 "$cfg" 2>/dev/null || true
}

oc_create_path_symlinks() {
    local home_oc="$HOME/.openclaw"

    if [ -d "/workspace" ] && [ ! -e "$home_oc" ]; then
        mkdir -p /workspace/.openclaw
        ln -sf /workspace/.openclaw "$home_oc"
        echo "Symlinked $home_oc -> /workspace/.openclaw (persistent storage)"
    fi
}
