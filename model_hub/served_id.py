"""Имя модели в API/OpenClaw: local-<slug>-gguf из имени файла, если не задан явный alias."""
from __future__ import annotations

import os
import re
from pathlib import Path

_SENTINEL_AUTO = "local-gguf"
_SLUG_MAX = 56


def compute_served_id(gguf_path: str, served_model_name_env: str | None = None) -> str:
    """
    Если в окружении SERVED_MODEL_NAME задан и это не «local-gguf» — используем его как alias.
    Иначе: из basename без .gguf строим slug (нижний регистр, не [a-z0-9] → «-»).
    """
    if not (gguf_path or "").strip():
        return _SENTINEL_AUTO

    o = (
        served_model_name_env
        if served_model_name_env is not None
        else (os.environ.get("SERVED_MODEL_NAME") or "")
    ).strip()
    if o and o != _SENTINEL_AUTO:
        return o

    stem = Path(gguf_path).stem
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "gguf"
    if len(slug) > _SLUG_MAX:
        slug = slug[:_SLUG_MAX].rstrip("-")
    return f"local-{slug}-gguf"
