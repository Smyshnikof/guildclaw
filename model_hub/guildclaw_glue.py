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
from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

GGUF_DIR = Path(os.environ.get("GUILDCLAW_GGUF_DIR", "/workspace/models/gguf"))
STATE_DIR = Path(os.environ.get("GUILDCLAW_STATE_DIR", "/workspace/.guildclaw"))
ACTIVE_FILE = STATE_DIR / "active.json"
CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
LLAMA_PID_FILE = Path(os.environ.get("GUILDCLAW_LLAMA_PID_FILE", "/tmp/guildclaw-llama.pid"))
SYNC_SCRIPT = Path(os.environ.get("GUILDCLAW_SYNC_SCRIPT", "")).resolve() if os.environ.get(
    "GUILDCLAW_SYNC_SCRIPT", ""
).strip() else Path(__file__).resolve().parent.parent / "scripts" / "sync_openclaw_llama.py"
SYNC_SCRIPT_DOCKER = Path("/opt/guildclaw/sync_openclaw_llama.py")

_hub_downloads: dict[str, dict[str, Any]] = {}
_hub_lock = __import__("threading").Lock()

_REPO_RE = re.compile(r"^[\w\-.]+/[\w\-.]+$")


def _hub_token() -> str:
    return os.environ.get("GUILDCLAW_HUB_TOKEN", "").strip()


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
        return JSONResponse({"models": _list_gguf()})

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
                headers["Authorization"] = f"Bearer {hf}"
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
    ) -> RedirectResponse:
        _check_hub(request, token)
        p = Path(path).resolve()
        if not str(p).startswith(str(GGUF_DIR.resolve())):
            raise HTTPException(400)
        sid = os.environ.get("SERVED_MODEL_NAME", "local-gguf").strip()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
            json.dump({"path": str(p), "served_id": sid}, f, indent=2)
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
        "<!DOCTYPE html><html><body style='background:#1e1e1e;color:#ccc;font-family:sans-serif;padding:40px'>"
        "<p>Нужен токен Hub: <code>/?token=…</code> (env <code>GUILDCLAW_HUB_TOKEN</code>) "
        "или заголовок <code>Authorization: Bearer …</code></p></body></html>",
        status_code=401,
    )
