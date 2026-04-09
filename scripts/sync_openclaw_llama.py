#!/usr/bin/env python3
"""Подставить served_id из active.json в openclaw.json (провайдер local-llama)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _guildclaw_root() -> Path:
    """Образ: /opt/guildclaw/sync_*.py; репозиторий: guildclaw/scripts/sync_*.py."""
    p = Path(__file__).resolve().parent
    return p if (p / "model_hub").is_dir() else p.parent


def _effective_context_window() -> int:
    """OpenClaw требует contextWindow >= 16000 в описании модели; llama -c должен совпадать."""
    raw = (os.environ.get("LLAMA_CTX_SIZE") or "16384").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 16384
    oc_min = int((os.environ.get("OPENCLAW_AGENT_MIN_CTX") or "16000").strip())
    return max(n, oc_min)


def _llama_api_key() -> str:
    """LLAMA_API_KEY из Dockerfile часто changeme; тогда берём VLLM_API_KEY (совместимость RunPod)."""
    k = (os.environ.get("LLAMA_API_KEY") or "").strip()
    if k and k != "changeme":
        return k
    v = (os.environ.get("VLLM_API_KEY") or "").strip()
    if v and v != "changeme":
        return v
    return k or v or "changeme"


def main() -> int:
    root = _guildclaw_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from model_hub.served_id import compute_served_id

    cfg_dir = os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw"))
    cfg_path = Path(cfg_dir) / "openclaw.json"
    if not cfg_path.is_file():
        return 0

    sid = os.environ.get("SERVED_MODEL_NAME", "local-gguf").strip()
    active = Path("/workspace/.guildclaw/active.json")
    display_suffix = ""
    if active.is_file():
        try:
            data_a = json.loads(active.read_text(encoding="utf-8"))
            path_a = data_a.get("path")
            sid_json = str(data_a.get("served_id") or "").strip()
            if path_a:
                pth = Path(path_a)
                if pth.is_file():
                    display_suffix = pth.name
                    if not sid_json or sid_json == "local-gguf":
                        new_sid = compute_served_id(str(pth))
                        if new_sid != sid_json:
                            data_a["served_id"] = new_sid
                            active.write_text(
                                json.dumps(data_a, indent=2) + "\n",
                                encoding="utf-8",
                            )
                            sid_json = new_sid
            sid = sid_json or sid
        except (OSError, json.JSONDecodeError):
            pass

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    data.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})[
        "primary"
    ] = f"local-llama/{sid}"

    prov = (
        data.setdefault("models", {})
        .setdefault("providers", {})
        .setdefault("local-llama", {})
    )
    prov["baseUrl"] = "http://localhost:8000/v1"
    prov["apiKey"] = _llama_api_key()
    prov["api"] = "openai-completions"
    models = prov.setdefault("models", [])
    human = (
        f"Local GGUF — {display_suffix}"
        if display_suffix
        else "Local GGUF (llama.cpp)"
    )
    if not models:
        models.append(
            {
                "id": sid,
                "name": human,
                "contextWindow": _effective_context_window(),
                "maxTokens": 4096,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }
        )
    else:
        models[0]["id"] = sid
        models[0]["name"] = human
        models[0]["contextWindow"] = _effective_context_window()

    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
