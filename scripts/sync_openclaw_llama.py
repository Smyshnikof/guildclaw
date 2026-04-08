#!/usr/bin/env python3
"""Подставить served_id из active.json в openclaw.json (провайдер local-llama)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    cfg_dir = os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw"))
    cfg_path = Path(cfg_dir) / "openclaw.json"
    if not cfg_path.is_file():
        return 0

    sid = os.environ.get("SERVED_MODEL_NAME", "local-gguf").strip()
    active = Path("/workspace/.guildclaw/active.json")
    if active.is_file():
        try:
            data_a = json.loads(active.read_text(encoding="utf-8"))
            sid = str(data_a.get("served_id") or sid).strip()
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
    prov["apiKey"] = os.environ.get("LLAMA_API_KEY", os.environ.get("VLLM_API_KEY", "changeme"))
    prov["api"] = "openai-completions"
    models = prov.setdefault("models", [])
    if not models:
        models.append(
            {
                "id": sid,
                "name": "Local GGUF (llama.cpp)",
                "contextWindow": int(os.environ.get("LLAMA_CTX_SIZE", "8192")),
                "maxTokens": 4096,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }
        )
    else:
        models[0]["id"] = sid
        models[0]["name"] = "Local GGUF (llama.cpp)"
        models[0]["contextWindow"] = int(os.environ.get("LLAMA_CTX_SIZE", "8192"))

    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
