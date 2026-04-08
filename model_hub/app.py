"""
Точка входа uvicorn: `model_hub.app:app`.
UI и логика скачивания — preset_downloader; Guildclaw (GGUF, токен, activate/delete) — guildclaw_glue.
"""
from .preset_downloader import app

__all__ = ["app"]
