"""
Guildclaw Model Hub — каталог GGUF, загрузка по URL, удаление, активация для llama-server.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

GGUF_DIR = Path(os.environ.get("GUILDCLAW_GGUF_DIR", "/workspace/models/gguf"))
STATE_DIR = Path(os.environ.get("GUILDCLAW_STATE_DIR", "/workspace/.guildclaw"))
ACTIVE_FILE = STATE_DIR / "active.json"
CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
LLAMA_PID_FILE = Path(os.environ.get("GUILDCLAW_LLAMA_PID_FILE", "/tmp/guildclaw-llama.pid"))

app = FastAPI(title="Guildclaw Model Hub")

_downloads: dict[str, dict[str, Any]] = {}
_download_lock = threading.Lock()


def _hub_token() -> str:
    return os.environ.get("GUILDCLAW_HUB_TOKEN", "").strip()


def _check_token(request: Request, token: Optional[str] = None) -> None:
    t = _hub_token()
    if not t:
        return
    q = token or request.query_params.get("token")
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        q = auth[7:].strip() or q
    if q != t:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def _load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"models": []}
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


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


def _is_active_path(path: str) -> bool:
    if not ACTIVE_FILE.is_file():
        return False
    try:
        with open(ACTIVE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("path") == path
    except (OSError, json.JSONDecodeError):
        return False


def _restart_llama() -> None:
    """Сигнал entrypoint-циклу: убить текущий llama-server."""
    if LLAMA_PID_FILE.is_file():
        try:
            pid = int(LLAMA_PID_FILE.read_text().strip())
            os.kill(pid, 15)
        except (ValueError, OSError, ProcessLookupError):
            pass
    subprocess.run(["pkill", "-x", "llama-server"], capture_output=True)


def _sync_openclaw() -> None:
    subprocess.run(
        [sys.executable, "/opt/guildclaw/sync_openclaw_llama.py"],
        env={**os.environ},
        check=False,
    )


@app.get("/health")
def health() -> PlainTextResponse:
    return PlainTextResponse("ok", status_code=200)


@app.get("/api/catalog")
def api_catalog(request: Request) -> JSONResponse:
    _check_token(request)
    return JSONResponse(_load_catalog())


@app.get("/api/models")
def api_models(request: Request) -> JSONResponse:
    _check_token(request)
    return JSONResponse({"models": _list_gguf()})


@app.get("/api/downloads/{job_id}")
def api_download_status(job_id: str, request: Request) -> JSONResponse:
    _check_token(request)
    with _download_lock:
        info = _downloads.get(job_id, {"status": "unknown"})
    return JSONResponse(info)


def _download_thread(job_id: str, url: str, filename: Optional[str]) -> None:
    with _download_lock:
        _downloads[job_id] = {"status": "running", "downloaded": 0, "total": 0, "error": None}
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    fname = filename or url.split("/")[-1].split("?")[0]
    if not fname.lower().endswith(".gguf"):
        with _download_lock:
            _downloads[job_id] = {"status": "error", "error": "Имя файла должно оканчиваться на .gguf"}
        return
    dest = GGUF_DIR / fname
    tmp = GGUF_DIR / f".{fname}.{job_id}.part"
    try:
        headers = {}
        hf = os.environ.get("HF_TOKEN", "").strip()
        if hf and "huggingface.co" in url:
            headers["Authorization"] = f"Bearer {hf}"
        with httpx.Client(timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                with _download_lock:
                    _downloads[job_id]["total"] = total
                n = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1024 * 1024):
                        f.write(chunk)
                        n += len(chunk)
                        with _download_lock:
                            _downloads[job_id]["downloaded"] = n
        tmp.rename(dest)
        with _download_lock:
            _downloads[job_id]["status"] = "done"
            _downloads[job_id]["path"] = str(dest.resolve())
    except Exception as e:
        with _download_lock:
            _downloads[job_id]["status"] = "error"
            _downloads[job_id]["error"] = str(e)
        if tmp.is_file():
            tmp.unlink(missing_ok=True)


@app.post("/api/download")
async def api_download(
    request: Request,
    url: str = Form(...),
    filename: Optional[str] = Form(None),
) -> JSONResponse:
    _check_token(request)
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Нужен http(s) URL")
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_download_thread, args=(job_id, url, filename), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@app.post("/api/activate")
async def api_activate(
    request: Request,
    path: str = Form(...),
    served_id: Optional[str] = Form(None),
) -> JSONResponse:
    _check_token(request)
    p = Path(path).resolve()
    if not str(p).startswith(str(GGUF_DIR.resolve())):
        raise HTTPException(400, "Путь вне каталога GGUF")
    if not p.is_file() or not p.name.lower().endswith(".gguf"):
        raise HTTPException(400, "Нет такого .gguf файла")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    sid = (served_id or os.environ.get("SERVED_MODEL_NAME", "local-gguf")).strip()
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump({"path": str(p), "served_id": sid}, f, indent=2)
    _restart_llama()
    _sync_openclaw()
    return JSONResponse({"ok": True, "path": str(p), "served_id": sid})


@app.delete("/api/models/{name}")
def api_delete(name: str, request: Request) -> JSONResponse:
    _check_token(request)
    if "/" in name or ".." in name:
        raise HTTPException(400, "Некорректное имя")
    p = (GGUF_DIR / name).resolve()
    if not str(p).startswith(str(GGUF_DIR.resolve())) or not p.is_file():
        raise HTTPException(404, "Файл не найден")
    if _is_active_path(str(p)):
        ACTIVE_FILE.unlink(missing_ok=True)
    p.unlink()
    _restart_llama()
    _sync_openclaw()
    return JSONResponse({"ok": True})


@app.get("/", response_class=HTMLResponse)
def ui(request: Request, token: Optional[str] = Query(None)) -> HTMLResponse:
    _check_token(request, token)
    cat = _load_catalog()
    tok_h = token or ""
    rows = "".join(
        f"""<tr><td>{m.get("label", m.get("id"))}</td><td>~{m.get("approx_gb", "?")} GB</td>
        <td><form method="post" action="/ui/download-preset" style="display:inline">
        <input type="hidden" name="token" value="{tok_h}"/>
        <input type="hidden" name="url" value="{m["url"]}"/>
        <input type="hidden" name="filename" value="{m["url"].split("/")[-1].split("?")[0]}"/>
        <button type="submit">Скачать</button></form></td></tr>"""
        for m in cat.get("models", [])
    )
    tok_q = f"?token={token}" if token else ""
    if _hub_token() and not token:
        return HTMLResponse(
            "<p>Укажите токен: <code>/</code><code>?token=...</code> (тот же, что GUILDCLAW_HUB_TOKEN)</p>",
            status_code=401,
        )
    html = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"/><title>Guildclaw — модели</title>
<style>
body {{ font-family: system-ui, sans-serif; background:#111; color:#e6e6e6; margin:24px; max-width:900px; }}
h1 {{ color:#7dd3fc; }} a {{ color:#7dd3fc; }}
table {{ width:100%; border-collapse:collapse; margin:16px 0; }}
th,td {{ border:1px solid #333; padding:8px; text-align:left; }}
button {{ background:#0369a1; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; }}
button.danger {{ background:#991b1b; }}
input[type=text] {{ width:100%; max-width:560px; padding:8px; background:#222; color:#fff; border:1px solid #444; }}
.section {{ margin:28px 0; padding:16px; background:#1a1a1a; border-radius:8px; }}
</style></head><body>
<h1>Guildclaw — GGUF модели</h1>
<p>Каталог на диске: <code>{GGUF_DIR}</code>. После «Активировать» конфиг OpenClaw обновится (провайдер <code>local-llama</code>, id модели = alias из <code>SERVED_MODEL_NAME</code> / active.json).</p>
<div class="section"><h2>Популярные</h2>
<table><thead><tr><th>Модель</th><th>~Размер</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
<div class="section"><h2>Своя ссылка (прямой URL на .gguf)</h2>
<form method="post" action="/ui/download-url"><input type="hidden" name="token" value="{tok_h}"/>
<input name="url" type="text" placeholder="https://huggingface.co/.../resolve/main/model.gguf" required/>
<button type="submit">Скачать</button></form></div>
<div class="section"><h2>Установленные</h2><div id="list">Загрузка…</div></div>
<script>
const tok = {json.dumps(token or "")};
async function refresh() {{
  const r = await fetch("/api/models" + (tok ? "?token="+encodeURIComponent(tok) : ""), {{headers: tok ? {{}} : {{}}}});
  if (!r.ok) {{ document.getElementById("list").textContent = "Ошибка API (нужен токен в URL ?token=)"; return; }}
  const j = await r.json();
  let h = "<table><thead><tr><th>Файл</th><th>Размер</th><th></th></tr></thead><tbody>";
  for (const m of j.models) {{
    const mb = (m.bytes/1024/1024).toFixed(0);
    h += "<tr><td>" + m.name + (m.active ? " <strong>(активна)</strong>" : "") + "</td><td>" + mb + " MB</td><td>";
    h += '<form method="post" action="/ui/activate" style="display:inline"><input type="hidden" name="token" value="'+tok+'"/><input type="hidden" name="path" value="'+m.path+'"/><button type="submit">Активировать</button></form> ';
    h += '<form method="post" action="/ui/delete" style="display:inline" onsubmit="return confirm(\\'Удалить файл?\\');"><input type="hidden" name="token" value="'+tok+'"/><input type="hidden" name="name" value="'+m.name+'"/><button type="submit" class="danger">Удалить</button></form>';
    h += "</td></tr>";
  }}
  h += "</tbody></table>";
  document.getElementById("list").innerHTML = h || "<p>Нет .gguf — скачайте из каталога или по URL.</p>";
}}
refresh();
setInterval(refresh, 8000);
</script>
</body></html>"""
    return HTMLResponse(html)


@app.post("/ui/download-preset")
async def ui_dl_preset(
    request: Request,
    url: str = Form(...),
    filename: Optional[str] = Form(None),
    token: Optional[str] = Form(None),
) -> HTMLResponse:
    _check_token(request, token)
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_download_thread, args=(job_id, url, filename), daemon=True).start()
    tok = token or ""
    return HTMLResponse(
        f'<p>Загрузка запущена. ID: <code>{job_id}</code></p>'
        f'<p><a href="/?token={tok}">Назад</a> — список обновится сам. Статус: <code>/api/downloads/{job_id}?token=...</code></p>',
        status_code=200,
    )


@app.post("/ui/download-url")
async def ui_dl_url(
    request: Request,
    url: str = Form(...),
    token: Optional[str] = Form(None),
) -> HTMLResponse:
    _check_token(request, token)
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_download_thread, args=(job_id, url.strip(), None), daemon=True).start()
    tok = token or ""
    return HTMLResponse(
        f'<p>Загрузка запущена. ID: <code>{job_id}</code></p><p><a href="/?token={tok}">Назад</a></p>',
        status_code=200,
    )


@app.post("/ui/activate")
async def ui_activate(
    request: Request,
    path: str = Form(...),
    token: Optional[str] = Form(None),
) -> HTMLResponse:
    _check_token(request, token)
    p = Path(path).resolve()
    if not str(p).startswith(str(GGUF_DIR.resolve())):
        raise HTTPException(400)
    sid = os.environ.get("SERVED_MODEL_NAME", "local-gguf")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump({"path": str(p), "served_id": sid}, f, indent=2)
    _restart_llama()
    _sync_openclaw()
    tok = token or ""
    return HTMLResponse(
        f"<p>Активировано. llama-server перезапускается.</p><p><a href=\"/?token={tok}\">Назад</a></p>"
    )


@app.post("/ui/delete")
async def ui_delete(
    request: Request,
    name: str = Form(...),
    token: Optional[str] = Form(None),
) -> HTMLResponse:
    _check_token(request, token)
    p = (GGUF_DIR / name).resolve()
    if str(p).startswith(str(GGUF_DIR.resolve())) and p.is_file():
        if _is_active_path(str(p)):
            ACTIVE_FILE.unlink(missing_ok=True)
        p.unlink()
        _restart_llama()
        _sync_openclaw()
    tok = token or ""
    return HTMLResponse(f"<p>Удалено.</p><p><a href=\"/?token={tok}\">Назад</a></p>")

