#!/usr/bin/env python3
"""
Guildclaw Mate — простой помощник в контейнере: ссылки, проверки сервисов, Telegram, вызов openclaw.

По умолчанию рабочая директория — /workspace (данные и openclaw workspace). Для корня ФС:
  guildclaw-mate --cwd / info
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _state_dir() -> Path:
    """
    В shell часто задан OPENCLAW_STATE_DIR=/root/.openclaw → это symlink на /workspace/.openclaw.
    Показываем канонический путь (.resolve()), чтобы не путать пользователя.
    """
    raw = (os.environ.get("OPENCLAW_STATE_DIR") or "").strip()
    if raw:
        base = Path(raw).expanduser()
    else:
        w = Path("/workspace/.openclaw")
        base = w if w.is_dir() else (Path.home() / ".openclaw")
    try:
        return base.resolve()
    except OSError:
        return base


def _workspace() -> Path:
    return Path(os.environ.get("OPENCLAW_WORKSPACE") or "/workspace/openclaw")


def _mask(s: str, keep: int = 4) -> str:
    s = (s or "").strip()
    if len(s) <= keep + 2:
        return "***" if s else "(пусто)"
    return s[:keep] + "…" + s[-2:]


def _chdir(path: Path) -> None:
    try:
        os.chdir(path)
    except OSError as e:
        print(f"guildclaw-mate: не удалось cd {path}: {e}", file=sys.stderr)
        sys.exit(1)


def _env_alt(primary: str, legacy: str) -> str:
    return (os.environ.get(primary) or os.environ.get(legacy) or "").strip()


def cmd_info(_: argparse.Namespace) -> int:
    pod = os.environ.get("RUNPOD_POD_ID", "").strip()
    pwd = os.environ.get("OPENCLAW_WEB_PASSWORD") or os.environ.get("A2GO_AUTH_TOKEN") or ""
    hub = _env_alt("MODEL_HUB_TOKEN", "GUILDCLAW_HUB_TOKEN")
    pair = _env_alt("PAIRING_DASH_TOKEN", "GUILDCLAW_PAIRING_DASH_TOKEN")
    tg_env = os.environ.get("TELEGRAM_BOT_TOKEN") or ""

    print("=== Guildclaw Mate — кратко ===\n")
    print("Папки:")
    print(f"  Рабочая область агента (AGENTS.md и т.д.): {_workspace()}")
    print(f"  Конфиг OpenClaw:                          {_state_dir() / 'openclaw.json'}")
    print(f"  Модели GGUF:                              /workspace/models/gguf")
    print(f"  Активная модель (Hub):                    /workspace/.guildclaw/active.json\n")

    if pod:
        base = f"https://{pod}"
        print("RunPod (подставьте токены в URL, если сервис их требует):")
        print(f"  Model Hub:         {base}-8080.proxy.runpod.net")
        print(f"  Node pairing:      {base}-8081.proxy.runpod.net")
        print(f"  OpenClaw Web UI:   {base}-18789.proxy.runpod.net")
        print(f"  LLM API (llama):   {base}-8000.proxy.runpod.net/v1\n")
    else:
        print("Локально:")
        print("  Model Hub:    http://localhost:8080")
        print("  Pairing:      http://localhost:8081")
        print("  OpenClaw UI:  http://localhost:18789")
        print("  LLM API:      http://localhost:8000/v1\n")

    print("Секреты (env, замаскированы):")
    print(f"  OPENCLAW_WEB_PASSWORD:          {_mask(pwd)}")
    print(f"  MODEL_HUB_TOKEN:                {_mask(hub)}")
    print(f"  PAIRING_DASH_TOKEN:             {_mask(pair)}")
    print(f"  TELEGRAM_BOT_TOKEN (env):       {_mask(tg_env)}\n")

    print("Как запускать (любой один вариант):")
    print("  guildclaw-mate doctor")
    print("  ./guildclaw-mate doctor          # из каталога /workspace, если есть лаунчер")
    print("  python3 /opt/guildclaw/scripts/guildclaw_mate.py doctor")
    print("  python3 ./guildclaw_mate.py doctor   # если скопировали .py в текущую папку")
    print("")
    print("Подкоманды:")
    print("  doctor   — порты и openclaw.json")
    print("  telegram — бот в конфиге")
    print("  oc …     — то же, что openclaw …")
    print("  openclaw devices pending  /  openclaw nodes pending")
    return 0


def _http_ok(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code in (401, 403, 404), f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def cmd_doctor(_: argparse.Namespace) -> int:
    checks = [
        ("Model Hub", "http://127.0.0.1:8080/health"),
        ("Pairing dash", "http://127.0.0.1:8081/health"),
        ("LLM API", "http://127.0.0.1:8000/v1/models"),
    ]
    ok_all = True
    print("=== Проверка сервисов (localhost) ===\n")
    for name, url in checks:
        ok, msg = _http_ok(url)
        ok_all = ok_all and ok
        sym = "OK " if ok else "FAIL"
        print(f"  [{sym}] {name}: {url} — {msg}")

    cfg = _state_dir() / "openclaw.json"
    print()
    if cfg.is_file():
        print(f"  [OK ] openclaw.json: {cfg}")
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            tg = (data.get("channels") or {}).get("telegram") or {}
            tok = str(tg.get("botToken") or "")
            en = tg.get("enabled", True)
            print(f"       telegram.enabled={en}, botToken={_mask(tok)}")
        except json.JSONDecodeError:
            print("       (ошибка чтения JSON)")
            ok_all = False
    else:
        print(f"  [FAIL] нет файла: {cfg}")
        ok_all = False

    print()
    oc = shutil.which("openclaw")
    print(f"  openclaw в PATH: {oc or '(не найден)'}\n")
    return 0 if ok_all else 1


def cmd_telegram(_: argparse.Namespace) -> int:
    cfg = _state_dir() / "openclaw.json"
    if not cfg.is_file():
        print(f"Нет {cfg}")
        return 1
    data = json.loads(cfg.read_text(encoding="utf-8"))
    tg = (data.get("channels") or {}).get("telegram") or {}
    tok = str(tg.get("botToken") or "")
    print("=== Telegram в openclaw.json ===\n")
    print(f"  enabled:  {tg.get('enabled', True)}")
    print(f"  botToken: {_mask(tok) if tok else '(не задан — добавьте TELEGRAM_BOT_TOKEN в RunPod и перезапустите под, см. DEPLOY.md)'}")
    env = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if env:
        print(f"  в env TELEGRAM_BOT_TOKEN: {_mask(env)} (при следующем старте пода запишется в конфиг)")
    return 0


def cmd_oc(ns: argparse.Namespace) -> int:
    args = list(ns.openclaw_args or [])
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("Укажите аргументы: guildclaw-mate oc -- devices pending", file=sys.stderr)
        return 2
    exe = shutil.which("openclaw")
    if not exe:
        print("openclaw не найден в PATH", file=sys.stderr)
        return 127
    return subprocess.call([exe, *args])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Guildclaw Mate — подсказки и проверки для образа Guildclaw / OpenClaw.",
    )
    parser.add_argument(
        "--cwd",
        default=(
            os.environ.get("MATE_CWD")
            or os.environ.get("GUILDCLAW_MATE_CWD")
            or "/workspace"
        ),
        help="Рабочая директория перед командами (по умолчанию /workspace; для корня ФС укажите /)",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_info = sub.add_parser("info", help="Пути, ссылки RunPod, маскированные секреты")
    p_info.set_defaults(func=cmd_info)

    p_doc = sub.add_parser("doctor", help="Health localhost + наличие openclaw.json")
    p_doc.set_defaults(func=cmd_doctor)

    p_tg = sub.add_parser("telegram", help="Статус telegram в openclaw.json")
    p_tg.set_defaults(func=cmd_telegram)

    p_oc = sub.add_parser("oc", help="Проброс в CLI openclaw (например: oc devices pending)")
    p_oc.add_argument(
        "openclaw_args",
        nargs=argparse.REMAINDER,
        default=[],
        help="аргументы для openclaw",
    )
    p_oc.set_defaults(func=cmd_oc)

    ns = parser.parse_args()
    _chdir(Path(ns.cwd).resolve())
    func = getattr(ns, "func", None)
    if func is None:
        return cmd_info(ns)
    return int(func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
