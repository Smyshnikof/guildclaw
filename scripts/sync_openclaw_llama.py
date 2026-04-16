#!/usr/bin/env python3
"""Подставить served_id из active.json в openclaw.json (провайдер local-llama)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


def _guildclaw_root() -> Path:
    """Образ: /opt/guildclaw/sync_*.py; репозиторий: guildclaw/scripts/sync_*.py."""
    p = Path(__file__).resolve().parent
    return p if (p / "model_hub").is_dir() else p.parent


def _compaction_reserve_floor() -> int:
    """Желаемый минимум буфера компакции (env); реальное значение режется под contextWindow."""
    raw = (os.environ.get("OPENCLAW_COMPACTION_RESERVE_TOKENS_FLOOR") or "20000").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 20000
    return max(n, 20000)


def _compaction_prompt_headroom() -> int:
    """
    Минимум токенов, который должен остаться под системный промпт, тулы и диалог
    (не под резерв компакции). Иначе precheck OpenClaw даёт promptBudgetBeforeReserve≈1
    при ctx=16k даже при «маленьком» пользовательском сообщении.
    """
    raw = (os.environ.get("OPENCLAW_COMPACTION_PROMPT_HEADROOM") or "12000").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 12000
    return max(h, 4096)


def _clamp_compaction_reserve(want: int, context_window: int) -> int:
    """
    reserveTokensFloor должен быть строго меньше contextWindow, иначе порог компакции
    (contextWindow - reserve) неположительный — OpenClaw сбрасывает чат с «Context limit exceeded».
    Апстрим клампит ~до 75% окна; плюс оставляем headroom под system/tools (см. precheck в логах).
    """
    cw = max(int(context_window), 4096)
    cap_ratio = cw * 72 // 100
    cap_margin = cw - 4096
    cap_head = cw - _compaction_prompt_headroom()
    cap = min(cap_ratio, cap_margin, max(cap_head, 2048))
    cap = max(cap, 2048)
    w = max(int(want), 1)
    return min(w, cap)


def _ensure_compaction_reserve(data: dict, context_window: int) -> None:
    target = _compaction_reserve_floor()
    reserve = _clamp_compaction_reserve(target, context_window)
    if reserve < target:
        print(
            f"guildclaw-sync: reserveTokensFloor {target} -> {reserve} "
            f"(contextWindow={context_window}; кламп по окну и по "
            f"OPENCLAW_COMPACTION_PROMPT_HEADROOM={_compaction_prompt_headroom()}). "
            f"Для reserve≈20000 поднимите LLAMA_CTX_SIZE (часто 32768, см. warn<32000 в OpenClaw).",
            file=sys.stderr,
        )

    agents_root = data.get("agents")
    if not isinstance(agents_root, dict):
        agents_root = data.setdefault("agents", {})
    for _key, block in agents_root.items():
        if not isinstance(block, dict):
            continue
        compaction = block.setdefault("compaction", {})
        cur = compaction.get("reserveTokensFloor")
        try:
            cur_i = int(cur)
        except (TypeError, ValueError):
            cur_i = 0
        merged = max(cur_i, reserve)
        compaction["reserveTokensFloor"] = _clamp_compaction_reserve(merged, context_window)


def _openclaw_agent_min_ctx() -> int:
    try:
        return max(int((os.environ.get("OPENCLAW_AGENT_MIN_CTX") or "16000").strip()), 1)
    except ValueError:
        return 16000


def _effective_context_window(active_override: Optional[object]) -> int:
    """OpenClaw требует contextWindow >= 16000; llama -c должен совпадать. active.json может задать llama_ctx_size."""
    oc_min = _openclaw_agent_min_ctx()
    max_hub = 1048576
    if active_override is not None and active_override != "":
        try:
            n = int(active_override)
            if n > 0:
                return min(max(n, oc_min), max_hub)
        except (TypeError, ValueError):
            pass
    raw = (os.environ.get("LLAMA_CTX_SIZE") or "16384").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 16384
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
    from model_hub.openclaw_model_input import effective_input_modes
    from model_hub.served_id import compute_served_id

    cfg_dir = os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw"))
    cfg_path = Path(cfg_dir) / "openclaw.json"
    if not cfg_path.is_file():
        return 0

    sid = os.environ.get("SERVED_MODEL_NAME", "local-gguf").strip()
    _rt = (os.environ.get("RUNTIME_STATE_DIR") or os.environ.get("GUILDCLAW_STATE_DIR") or "").strip()
    active = Path(_rt or "/workspace/.guildclaw") / "active.json"
    display_suffix = ""
    ctx_override: Optional[object] = None
    data_a: dict[str, Any] = {}
    if active.is_file():
        try:
            data_a = json.loads(active.read_text(encoding="utf-8"))
            ctx_override = data_a.get("llama_ctx_size")
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
            data_a = {}

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    data.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})[
        "primary"
    ] = f"local-llama/{sid}"

    cw = _effective_context_window(ctx_override)
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
    inputs = effective_input_modes(data_a)
    if not models:
        models.append(
            {
                "id": sid,
                "name": human,
                "contextWindow": cw,
                "maxTokens": 4096,
                "reasoning": False,
                "input": inputs,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }
        )
    else:
        models[0]["id"] = sid
        models[0]["name"] = human
        models[0]["contextWindow"] = cw
        models[0]["input"] = inputs

    try:
        cw_eff = int(models[0].get("contextWindow") or cw)
    except (TypeError, ValueError):
        cw_eff = cw
    _ensure_compaction_reserve(data, cw_eff)

    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
