"""
Guildclaw: токен Hub, GGUF-список, активация/удаление, синхронизация OpenClaw.
Подключается к FastAPI из preset_downloader без смены его HTML/CSS.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from .served_id import compute_served_id
from .stack_env import env_path, env_str
from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

GGUF_DIR = env_path("MODEL_GGUF_DIR", "GUILDCLAW_GGUF_DIR", default="/workspace/models/gguf")
STATE_DIR = env_path("RUNTIME_STATE_DIR", "GUILDCLAW_STATE_DIR", default="/workspace/.guildclaw")
ACTIVE_FILE = STATE_DIR / "active.json"
CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
LLAMA_PID_FILE = env_path(
    "LLAMA_PID_FILE", "GUILDCLAW_LLAMA_PID_FILE", default="/tmp/guildclaw-llama.pid"
)
_sync_raw = env_str("OPENCLAW_LLAMA_SYNC_SCRIPT", "GUILDCLAW_SYNC_SCRIPT")
SYNC_SCRIPT = (
    Path(_sync_raw).resolve()
    if _sync_raw
    else Path(__file__).resolve().parent.parent / "scripts" / "sync_openclaw_llama.py"
)
SYNC_SCRIPT_DOCKER = Path("/opt/guildclaw/sync_openclaw_llama.py")

_hub_downloads: dict[str, dict[str, Any]] = {}
_hub_lock = __import__("threading").Lock()

_REPO_RE = re.compile(r"^[\w\-.]+/[\w\-.]+$")


def _hub_token() -> str:
    return env_str("MODEL_HUB_TOKEN", "GUILDCLAW_HUB_TOKEN")


def hf_authorization_bearer_header(raw_token: str, source_label: str) -> Optional[str]:
    """
    Значение заголовка ``Authorization`` для запросов к Hugging Face.
    В ``http.client``/urllib заголовки кодируются как Latin-1; кириллица или «умные» кавычки
    в токене дают ``UnicodeEncodeError: 'latin-1' codec can't encode...``.
    """
    t = (raw_token or "").strip()
    if not t:
        return None
    try:
        t.encode("latin-1")
    except UnicodeEncodeError as e:
        raise ValueError(
            f"{source_label}: в токене есть символы вне Latin-1 "
            "(часто кириллица, кавычки из Word или невидимые символы). "
            "Нужен настоящий токен Hugging Face: https://huggingface.co/settings/tokens "
            "(обычно начинается с hf_, только латиница, цифры и _-)."
        ) from e
    return f"Bearer {t}"


def _token_from_request(request: Request) -> Optional[str]:
    q = request.query_params.get("token")
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        q = auth[7:].strip() or q
    return q


def _check_hub(request: Request, form_token: Optional[str] = None) -> None:
    t = _hub_token()
    if not t:
        return
    if _token_from_request(request) == t:
        return
    if form_token is not None and form_token == t:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing hub token")


def _openclaw_agent_min_ctx() -> int:
    try:
        return max(int((os.environ.get("OPENCLAW_AGENT_MIN_CTX") or "16000").strip()), 1)
    except ValueError:
        return 16000


# Верхняя граница для Hub / active.json (1M токенов); llama.cpp и VRAM могут не вытянуть — пользователь сам оценивает.
MAX_LLAMA_CTX_SIZE = 1048576


def _validate_llama_ctx_int(n: int) -> None:
    oc_min = _openclaw_agent_min_ctx()
    if n < oc_min:
        raise HTTPException(
            status_code=400,
            detail=f"Контекст не меньше {oc_min} (минимум OpenClaw).",
        )
    if n > MAX_LLAMA_CTX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"llama_ctx_size слишком большой (макс. {MAX_LLAMA_CTX_SIZE}).",
        )


def _env_llama_ctx_clamped() -> int:
    raw = (os.environ.get("LLAMA_CTX_SIZE") or "16384").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 16384
    return max(n, _openclaw_agent_min_ctx())


def _active_llama_ctx_override() -> Optional[int]:
    if not ACTIVE_FILE.is_file():
        return None
    try:
        d = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        v = d.get("llama_ctx_size")
        if v is None or v == "":
            return None
        n = int(v)
        if n < 1:
            return None
        n = max(n, _openclaw_agent_min_ctx())
        return min(n, MAX_LLAMA_CTX_SIZE)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _is_active_path(path: str) -> bool:
    if not ACTIVE_FILE.is_file():
        return False
    try:
        with open(ACTIVE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("path") == path
    except (OSError, json.JSONDecodeError):
        return False


def _list_gguf() -> list[dict[str, Any]]:
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(GGUF_DIR.glob("*.gguf")):
        try:
            st = p.stat()
            out.append(
                {
                    "name": p.name,
                    "path": str(p.resolve()),
                    "bytes": st.st_size,
                    "active": _is_active_path(str(p.resolve())),
                }
            )
        except OSError:
            continue
    return out


def _restart_llama() -> None:
    if LLAMA_PID_FILE.is_file():
        try:
            pid = int(LLAMA_PID_FILE.read_text().strip())
            os.kill(pid, 15)
        except (ValueError, OSError, ProcessLookupError):
            pass
    subprocess.run(["pkill", "-x", "llama-server"], capture_output=True)


def _sync_openclaw() -> None:
    script = SYNC_SCRIPT_DOCKER if SYNC_SCRIPT_DOCKER.is_file() else SYNC_SCRIPT
    if script.is_file():
        subprocess.run([sys.executable, str(script)], env={**os.environ}, check=False)


def _redirect_home(**extra: str) -> RedirectResponse:
    q: dict[str, str] = {}
    extra = dict(extra)
    hub_t = extra.pop("hub_token", None)
    env_t = _hub_token()
    eff = (hub_t or "").strip() or env_t
    if eff:
        q["token"] = eff
    q.update({k: v for k, v in extra.items() if v})
    path = "/?" + urlencode(q) if q else "/"
    return RedirectResponse(url=path, status_code=303)


def _hf_resolve_url(repo: str, filename: str, revision: str) -> str:
    repo = repo.strip().strip("/")
    filename = filename.strip().lstrip("/")
    revision = (revision or "main").strip()
    return f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"


def _load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"models": []}
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def register_guildclaw(app: Any) -> None:
    import threading
    import uuid

    @app.middleware("http")
    async def _mark_hub_ui(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Guildclaw-Hub-UI"] = "preset-downloader"
        return response

    @app.get("/api/catalog")
    def api_catalog(request: Request) -> JSONResponse:
        _check_hub(request)
        return JSONResponse(_load_catalog())

    @app.get("/api/models")
    def api_models(request: Request) -> JSONResponse:
        _check_hub(request)
        ov = _active_llama_ctx_override()
        env_c = _env_llama_ctx_clamped()
        return JSONResponse(
            {
                "models": _list_gguf(),
                "llama_ctx_env": env_c,
                "llama_ctx_override": ov,
                "llama_ctx_effective": ov if ov is not None else env_c,
                "llama_ctx_max": MAX_LLAMA_CTX_SIZE,
            }
        )

    @app.post("/api/apply_ctx")
    async def api_apply_ctx(
        request: Request,
        llama_ctx_size: Optional[str] = Form(None),
        reset_ctx: Optional[str] = Form(None),
    ) -> JSONResponse:
        """Поменять только llama_ctx_size в active.json (без смены .gguf), перезапуск llama-server."""
        _check_hub(request)
        if not ACTIVE_FILE.is_file():
            raise HTTPException(
                status_code=400,
                detail="Нет active.json — сначала активируйте модель на вкладке «Мои GGUF».",
            )
        try:
            data = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Не удалось прочитать active.json.")
        path_raw = str(data.get("path") or "").strip()
        if not path_raw:
            raise HTTPException(status_code=400, detail="В active.json нет path к модели.")
        pth = Path(path_raw)
        if not pth.is_file():
            raise HTTPException(
                status_code=400,
                detail="Файл модели по path не найден на диске — активируйте существующий .gguf.",
            )

        reset = (reset_ctx or "").strip().lower() in ("1", "true", "yes", "on")
        if reset:
            data.pop("llama_ctx_size", None)
            msg = "Переопределение снято: используется LLAMA_CTX_SIZE из окружения."
        else:
            raw = (llama_ctx_size or "").strip()
            if not raw:
                raise HTTPException(
                    status_code=400,
                    detail="Укажите llama_ctx_size или отправьте reset_ctx=1 для сброса.",
                )
            try:
                n = int(raw)
            except ValueError:
                raise HTTPException(status_code=400, detail="llama_ctx_size: нужно целое число.") from None
            _validate_llama_ctx_int(n)
            data["llama_ctx_size"] = n
            msg = "Контекст обновлён, llama-server перезапускается."

        with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        _restart_llama()
        _sync_openclaw()

        ov = _active_llama_ctx_override()
        env_c = _env_llama_ctx_clamped()
        return JSONResponse(
            {
                "ok": True,
                "message": msg,
                "llama_ctx_env": env_c,
                "llama_ctx_override": ov,
                "llama_ctx_effective": ov if ov is not None else env_c,
            }
        )

    @app.get("/api/downloads/{job_id}")
    def api_download_status(job_id: str, request: Request) -> JSONResponse:
        _check_hub(request)
        with _hub_lock:
            info = _hub_downloads.get(job_id, {"status": "unknown"})
        return JSONResponse(info)

    def _download_thread(job_id: str, url: str, filename: Optional[str]) -> None:
        with _hub_lock:
            _hub_downloads[job_id] = {"status": "running", "downloaded": 0, "total": 0, "error": None}
        GGUF_DIR.mkdir(parents=True, exist_ok=True)
        fname = filename or url.split("/")[-1].split("?")[0]
        if not fname.lower().endswith(".gguf"):
            with _hub_lock:
                _hub_downloads[job_id] = {"status": "error", "error": "Нужен файл .gguf"}
            return
        dest = GGUF_DIR / fname
        tmp = GGUF_DIR / f".{fname}.{job_id}.part"
        try:
            headers: dict[str, str] = {}
            hf = os.environ.get("HF_TOKEN", "").strip()
            if hf and "huggingface.co" in url:
                auth = hf_authorization_bearer_header(hf, "HF_TOKEN")
                if auth:
                    headers["Authorization"] = auth
            with httpx.Client(timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True) as client:
                with client.stream("GET", url, headers=headers) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length") or 0)
                    with _hub_lock:
                        _hub_downloads[job_id]["total"] = total
                    n = 0
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1024 * 1024):
                            f.write(chunk)
                            n += len(chunk)
                            with _hub_lock:
                                _hub_downloads[job_id]["downloaded"] = n
            tmp.rename(dest)
            with _hub_lock:
                _hub_downloads[job_id]["status"] = "done"
                _hub_downloads[job_id]["path"] = str(dest.resolve())
        except Exception as e:
            with _hub_lock:
                _hub_downloads[job_id]["status"] = "error"
                _hub_downloads[job_id]["error"] = str(e)
            if tmp.is_file():
                tmp.unlink(missing_ok=True)

    @app.post("/api/download")
    async def api_download(
        request: Request,
        url: str = Form(...),
        filename: Optional[str] = Form(None),
    ) -> JSONResponse:
        _check_hub(request)
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "Нужен http(s) URL")
        job_id = uuid.uuid4().hex[:12]
        threading.Thread(target=_download_thread, args=(job_id, url, filename), daemon=True).start()
        return JSONResponse({"job_id": job_id})

    @app.post("/ui/activate")
    async def ui_activate(
        request: Request,
        path: str = Form(...),
        token: Optional[str] = Form(None),
        llama_ctx_size: Optional[str] = Form(None),
    ) -> RedirectResponse:
        _check_hub(request, token)
        p = Path(path).resolve()
        if not str(p).startswith(str(GGUF_DIR.resolve())):
            raise HTTPException(400)
        sid = compute_served_id(str(p))
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"path": str(p), "served_id": sid}
        raw_ctx = (llama_ctx_size or "").strip()
        if raw_ctx:
            try:
                n = int(raw_ctx)
            except ValueError:
                raise HTTPException(400, detail="llama_ctx_size: нужно целое число") from None
            _validate_llama_ctx_int(n)
            payload["llama_ctx_size"] = n
        with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        _restart_llama()
        _sync_openclaw()
        return _redirect_home(
            notice="Модель активирована, llama-server перезапускается.",
            hub_token=token or "",
        )

    @app.post("/ui/delete")
    async def ui_delete(
        request: Request,
        name: str = Form(...),
        token: Optional[str] = Form(None),
    ) -> RedirectResponse:
        _check_hub(request, token)
        p = (GGUF_DIR / name).resolve()
        if str(p).startswith(str(GGUF_DIR.resolve())) and p.is_file():
            if _is_active_path(str(p)):
                ACTIVE_FILE.unlink(missing_ok=True)
            p.unlink()
            _restart_llama()
            _sync_openclaw()
        return _redirect_home(notice="Файл удалён.", hub_token=token or "")


def check_hub_request(request: Request, form_token: Optional[str] = None) -> None:
    _check_hub(request, form_token)


def hub_index_gate(request: Request) -> Optional[HTMLResponse]:
    t = _hub_token()
    if not t:
        return None
    if _token_from_request(request) == t:
        return None
    return HTMLResponse(
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'/>"
        "<title>Model Hub — вход</title></head>"
        "<body style='min-height:100vh;margin:0;display:flex;align-items:center;justify-content:center;"
        "box-sizing:border-box;background:#1e1e1e;color:#ccc;font-family:system-ui,sans-serif;padding:24px'>"
        "<div style='width:100%;max-width:420px;text-align:center'>"
        "<h2 style='color:#e8e8e8;margin:0 0 12px'>Guildclaw Model Hub</h2>"
        "<p style='margin:0 0 20px;line-height:1.5'>Нужен тот же токен, что в "
        "<code style='word-break:break-all'>MODEL_HUB_TOKEN</code> на сервере.</p>"
        "<p style='margin:0 0 12px'>"
        "<input id='t' type='password' placeholder='Токен Hub' autocomplete='current-password' "
        "style='width:100%;padding:12px;background:#111;border:1px solid #444;border-radius:8px;color:#fff;box-sizing:border-box'/>"
        "</p>"
        "<p style='margin:0 0 16px'>"
        "<button type='button' onclick='login()' style='padding:10px 22px;background:#3b82f6;color:#fff;"
        "border:none;border-radius:8px;cursor:pointer;font-size:15px'>Войти</button></p>"
        "<p style='font-size:13px;color:#888;margin:0;line-height:1.45'>После входа токен сохранится в браузере (localStorage).</p>"
        "<script>"
        "function login(){var v=document.getElementById('t').value.trim();if(!v)return;"
        "try{localStorage.setItem('guildclaw_hub_token',v);}catch(e){}"
        "location.href='/?token='+encodeURIComponent(v);}"
        "</script></div></body></html>",
        status_code=401,
    )
