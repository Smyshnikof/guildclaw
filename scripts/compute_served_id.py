#!/usr/bin/env python3
"""CLI для entrypoint: печатает served_id по пути к .gguf (см. model_hub.served_id)."""
from __future__ import annotations

import sys
from pathlib import Path

# Репозиторий: guildclaw/scripts/… → корень guildclaw; образ: /opt/guildclaw/scripts/…
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from model_hub.served_id import compute_served_id  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: compute_served_id.py <path/to/model.gguf>\n")
        sys.exit(2)
    print(compute_served_id(sys.argv[1]))
