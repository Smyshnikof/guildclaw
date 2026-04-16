"""Короткие имена переменных окружения; префикс GUILDCLAW_* — устаревший fallback."""
from __future__ import annotations

import os
from pathlib import Path


def env_str(*keys: str, default: str = "") -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return default


def env_path(*keys: str, default: str) -> Path:
    return Path(env_str(*keys, default=default) or default)
