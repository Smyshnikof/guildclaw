"""
Карточка local-llama в openclaw.json: поле models[].input (text / image / audio).
Переопределение из active.json (openclaw_model_input) имеет приоритет над env.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

# Модальности, которые мы разрешаем задавать из Hub (остальное — только ручной JSON в active.json).
_ALLOWED_MODALITIES = frozenset({"text", "image", "audio"})


def input_modes_from_env() -> list[str]:
    """Только env: LOCAL_LLAMA_VISION, OPENCLAW_LOCAL_MODEL_INPUT."""
    custom = (
        os.environ.get("OPENCLAW_LOCAL_MODEL_INPUT")
        or os.environ.get("GUILDCLAW_OPENCLAW_LOCAL_MODEL_INPUT")
        or ""
    ).strip()
    if custom:
        try:
            arr = json.loads(custom)
            if isinstance(arr, list) and arr and all(isinstance(x, str) for x in arr):
                return list(arr)
        except json.JSONDecodeError:
            pass
    flag = (
        os.environ.get("LOCAL_LLAMA_VISION") or os.environ.get("GUILDCLAW_LOCAL_LLAMA_VISION") or ""
    ).strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return ["text", "image"]
    return ["text"]


def input_modes_from_active(active: dict[str, Any]) -> Optional[list[str]]:
    """
    openclaw_model_input в active.json — JSON-массив строк, напр. ["text","image"].
    None / отсутствие ключа — использовать env.
    """
    if not active:
        return None
    v = active.get("openclaw_model_input")
    if v is None:
        return None
    if not isinstance(v, list) or len(v) == 0:
        return None
    out: list[str] = []
    for x in v:
        if not isinstance(x, str) or not x.strip():
            return None
        t = x.strip().lower()
        if t not in _ALLOWED_MODALITIES:
            return None
        out.append(t)
    if "text" not in out:
        out.insert(0, "text")
    return out


def effective_input_modes(active: Optional[dict[str, Any]]) -> list[str]:
    if active:
        o = input_modes_from_active(active)
        if o is not None:
            return o
    return input_modes_from_env()


def apply_input_mode_to_payload(payload: dict[str, Any], mode: Optional[str]) -> None:
    """
    mode: env — убрать ключ (только env); text — ["text"]; vision — ["text","image"].
    """
    m = (mode or "env").strip().lower()
    if m in ("env", "", "default"):
        payload.pop("openclaw_model_input", None)
    elif m == "text":
        payload["openclaw_model_input"] = ["text"]
    elif m in ("vision", "text_image", "multimodal"):
        payload["openclaw_model_input"] = ["text", "image"]
    else:
        raise ValueError(f"Неизвестный openclaw_input_mode: {mode!r}")
