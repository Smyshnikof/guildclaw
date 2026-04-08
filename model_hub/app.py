"""
Guildclaw Model Hub — UI в духе ComfyUI Preset Downloader: пресеты, HF (URL + repo), мои модели.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

GGUF_DIR = Path(os.environ.get("GUILDCLAW_GGUF_DIR", "/workspace/models/gguf"))
STATE_DIR = Path(os.environ.get("GUILDCLAW_STATE_DIR", "/workspace/.guildclaw"))
ACTIVE_FILE = STATE_DIR / "active.json"
CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"
LLAMA_PID_FILE = Path(os.environ.get("GUILDCLAW_LLAMA_PID_FILE", "/tmp/guildclaw-llama.pid"))

app = FastAPI(title="Guildclaw Model Hub")

_downloads: dict[str, dict[str, Any]] = {}
_download_lock = threading.Lock()

_REPO_RE = re.compile(r"^[\w\-.]+/[\w\-.]+$")


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


def _redirect_home(token: str, **extra: str) -> RedirectResponse:
    q: dict[str, str] = {}
    if token:
        q["token"] = token
    q.update({k: v for k, v in extra.items() if v})
    path = "/?" + urlencode(q) if q else "/"
    return RedirectResponse(url=path, status_code=303)


def _hf_resolve_url(repo: str, filename: str, revision: str) -> str:
    repo = repo.strip().strip("/")
    filename = filename.strip().lstrip("/")
    revision = (revision or "main").strip()
    return f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"


def _collect_categories(models: list[dict[str, Any]]) -> list[str]:
    cats: set[str] = set()
    for m in models:
        c = m.get("category") or "Разное"
        cats.add(str(c))
    return sorted(cats)


def _html_preset_cards(models: list[dict[str, Any]], tok: str) -> str:
    parts: list[str] = []
    tok_a = html.escape(tok, quote=True)
    for m in models:
        mid = html.escape(m.get("id", ""), quote=True)
        label = html.escape(m.get("label", m.get("id", "")), quote=True)
        desc = html.escape(m.get("description", ""), quote=True)
        cat = html.escape(m.get("category", "Разное"), quote=True)
        gb = html.escape(str(m.get("approx_gb", "?")), quote=True)
        url = m["url"]
        fn = url.split("/")[-1].split("?")[0]
        url_a = html.escape(url, quote=True)
        fn_a = html.escape(fn, quote=True)
        search = html.escape(
            f"{m.get('label', '')} {m.get('description', '')} {m.get('category', '')} {' '.join(m.get('tags', []))}".lower(),
            quote=True,
        )
        parts.append(
            f"""<div class="preset-card" data-category="{cat}" data-search="{search}">
  <div class="preset-name">{label}</div>
  <div class="preset-desc">{desc}</div>
  <div class="preset-info">~{gb} GB · {cat}</div>
  <form method="post" action="/ui/download-preset" style="margin-top:12px;">
    <input type="hidden" name="token" value="{tok_a}"/>
    <input type="hidden" name="url" value="{url_a}"/>
    <input type="hidden" name="filename" value="{fn_a}"/>
    <button type="submit" class="btn btn-preset">Скачать пресет</button>
  </form>
</div>"""
        )
    return "\n".join(parts)


def _html_category_filters(categories: list[str]) -> str:
    chips = [
        '<button type="button" class="category-filter all active" data-cat="__all__" '
        'onclick="filterCategory(this)">Все</button>'
    ]
    for c in categories:
        ca = html.escape(c, quote=True)
        ce = html.escape(c)
        chips.append(
            f'<button type="button" class="category-filter" data-cat="{ca}" '
            f'onclick="filterCategory(this)">{ce}</button>'
        )
    return "\n".join(chips)


def _render_index(token: Optional[str], job_id: Optional[str], notice: Optional[str]) -> str:
    tok = token or ""
    cat = _load_catalog()
    models = cat.get("models", [])
    categories = _collect_categories(models)
    cards = _html_preset_cards(models, tok)
    filters = _html_category_filters(categories)
    gguf_esc = html.escape(str(GGUF_DIR))
    tok_js = json.dumps(tok)
    job_js = json.dumps(job_id or "")
    notice_js = json.dumps(notice or "")
    hf_hint = html.escape(
        "Для приватных репозиториев задайте HF_TOKEN в окружении контейнера или вставьте полный URL с токеном (не рекомендуется в логах)."
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Guildclaw — GGUF Model Hub</title>
  <style>
    :root {{ --bg:#1e1e1e; --card:#282828; --text:#fff; --muted:#9ca3af; --accent:#fff; }}
    html,body {{ margin:0; padding:0; background:var(--bg); color:var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, sans-serif; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}
    .title {{ font-size: 32px; font-weight: 800; margin: 0 0 8px; color: var(--accent); text-align: center;
      text-shadow: 0 0 10px rgba(255,255,255,0.25); }}
    .subtitle {{ margin:0 0 28px; color:var(--muted); text-align: center; font-size: 15px; }}
    .tabs {{ display: flex; gap: 8px; margin-bottom: 20px; justify-content: center; flex-wrap: wrap; }}
    .tab {{ padding: 10px 18px; background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; cursor: pointer; transition: all 0.2s; }}
    .tab:hover {{ border-color: var(--accent); }}
    .tab.active {{ background: var(--accent); color: var(--bg); font-weight: 700; }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}
    .card {{ background: var(--card); border:1px solid #3a3a3a; border-radius: 12px; padding: 24px; box-sizing: border-box; margin-bottom: 20px; }}
    .row {{ display:grid; grid-template-columns: 200px 1fr; gap:16px; align-items:center; margin:16px 0; }}
    @media (max-width: 640px) {{ .row {{ grid-template-columns: 1fr; }} }}
    .row-full {{ margin: 16px 0; }}
    input[type=text], input[type=password], select {{
      width:100%; padding:12px 16px; background:#1a1a1a; border:1px solid #3a3a3a; color:var(--text); border-radius:8px; box-sizing: border-box; }}
    .btn {{ display:inline-flex; align-items:center; gap:8px; padding:12px 20px; background: rgba(255,255,255,0.9); color:var(--bg);
      font-weight:700; border:2px solid rgba(255,255,255,0.5); border-radius:8px; cursor:pointer; transition: all 0.2s; border:none; }}
    .btn:hover {{ background: var(--accent); color:var(--bg); }}
    .btn-preset {{
      background: rgba(34, 197, 94, 0.9); color: white; border: 2px solid rgba(34, 197, 94, 0.5);
      box-shadow: 0 4px 12px rgba(34, 197, 94, 0.25); width: 100%; justify-content: center; }}
    .btn-preset:hover {{ background: rgb(34, 197, 94); color: white; box-shadow: 0 8px 20px rgba(34, 197, 94, 0.45); }}
    .btn-hf {{
      background: rgba(255, 193, 7, 0.95); color: #111; border: 2px solid rgba(255, 193, 7, 0.6);
      box-shadow: 0 4px 12px rgba(255, 193, 7, 0.25); }}
    .btn-hf:hover {{ background: rgb(255, 193, 7); box-shadow: 0 8px 20px rgba(255, 193, 7, 0.45); }}
    .btn-danger {{ background: rgba(185, 28, 28, 0.9); color: #fff; border: 2px solid rgba(185,28,28,0.5); }}
    .btn-danger:hover {{ background: rgb(185, 28, 28); }}
    .hint {{ background:#1a1a1a; border:1px dashed #3a3a3a; padding:16px; border-radius:8px; margin-bottom:20px; color: var(--muted); font-size: 14px; line-height: 1.5; }}
    .search-container {{ margin-bottom: 16px; position: relative; }}
    .search-input {{ width: 100%; padding: 12px 16px 12px 44px; background: #1a1a1a; border: 1px solid #3a3a3a;
      color: var(--text); border-radius: 8px; box-sizing: border-box; font-size: 14px; }}
    .search-icon {{ position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: var(--muted); pointer-events: none; }}
    .category-filters {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }}
    .category-filter {{ padding: 8px 16px; background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; cursor: pointer;
      transition: all 0.2s; font-size: 14px; color: var(--muted); }}
    .category-filter:hover {{ border-color: var(--accent); background: #222; color: var(--text); }}
    .category-filter.active {{ background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }}
    .preset-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin: 20px 0; }}
    .preset-card {{ background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; padding: 16px; transition: all 0.2s; }}
    .preset-card:hover {{ border-color: var(--accent); background: #222; }}
    .preset-card.hidden {{ display: none; }}
    .preset-name {{ font-weight: 700; margin-bottom: 8px; color: var(--accent); font-size: 16px; }}
    .preset-desc {{ color: var(--muted); font-size: 14px; margin-bottom: 8px; line-height: 1.45; }}
    .preset-info {{ font-size: 12px; color: var(--muted); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }}
    .banner {{ background: #1a3a2a; border: 1px solid #2d6a4f; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }}
    .banner.err {{ background: #3a1a1a; border-color: #6a2d2d; }}
    table.data {{ width:100%; border-collapse:collapse; margin-top:12px; }}
    table.data th, table.data td {{ border:1px solid #3a3a3a; padding:10px 12px; text-align:left; }}
    table.data th {{ background:#1a1a1a; color: var(--muted); font-weight: 600; }}
    h3 {{ margin-top: 0; font-size: 18px; }}
    a {{ color: #7dd3fc; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1 class="title">Guildclaw Model Hub</h1>
    <p class="subtitle">Пресеты GGUF · прямая ссылка · HuggingFace репозиторий · активация для llama-server</p>
    <p class="subtitle mono">Каталог на диске: {gguf_esc}</p>

    <div id="banner-slot"></div>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('presets')">Пресеты</div>
      <div class="tab" onclick="switchTab('huggingface')">HuggingFace</div>
      <div class="tab" onclick="switchTab('installed')">Мои модели</div>
    </div>

    <div id="presets-panel" class="tab-content active">
      <div class="card">
        <h3>Готовые пресеты</h3>
        <div class="search-container">
          <span class="search-icon">🔍</span>
          <input type="text" class="search-input" id="preset-search" placeholder="Поиск по названию, описанию, категории…" oninput="filterPresets()"/>
        </div>
        <div class="category-filters">{filters}</div>
        <div class="preset-grid" id="preset-grid">{cards}</div>
      </div>
    </div>

    <div id="huggingface-panel" class="tab-content">
      <div class="card">
        <div class="hint">
          <b>Как скачать?</b> Либо вставьте <b>прямую ссылку</b> на файл <span class="mono">.gguf</span> (как на странице файла в HF → «copy download link»),
          либо укажите <b>репозиторий</b> и имя файла — мы соберём URL вида
          <span class="mono">huggingface.co/…/resolve/ветка/файл</span>. {hf_hint}
        </div>
        <div class="tabs" style="margin-bottom: 16px;">
          <div class="tab active" onclick="switchHFMethod('url')">Прямая ссылка</div>
          <div class="tab" onclick="switchHFMethod('repo')">HuggingFace Repo</div>
        </div>

        <form id="hf-url-form" method="post" action="/ui/download-url">
          <input type="hidden" name="token" value="{html.escape(tok, quote=True)}"/>
          <div class="row">
            <label for="hf_url">URL файла .gguf</label>
            <input id="hf_url" type="text" name="url" required
              placeholder="https://huggingface.co/user/model/resolve/main/model-Q4_K_M.gguf"/>
          </div>
          <div class="row">
            <label for="hf_url_fn">Имя файла (опционально)</label>
            <input id="hf_url_fn" type="text" name="filename" placeholder="оставьте пустым — из URL"/>
          </div>
          <div class="row-full">
            <button type="submit" class="btn btn-hf">Скачать по ссылке</button>
          </div>
        </form>

        <form id="hf-repo-form" method="post" action="/ui/download-hf-repo" style="display:none;">
          <input type="hidden" name="token" value="{html.escape(tok, quote=True)}"/>
          <div class="row">
            <label for="hf_repo">Репозиторий</label>
            <input id="hf_repo" type="text" name="repo" required placeholder="bartowski/Qwen2.5-7B-Instruct-GGUF"/>
          </div>
          <div class="row">
            <label for="hf_file">Файл .gguf</label>
            <input id="hf_file" type="text" name="filename" required placeholder="Qwen2.5-7B-Instruct-Q4_K_M.gguf"/>
          </div>
          <div class="row">
            <label for="hf_rev">Ветка / revision</label>
            <input id="hf_rev" type="text" name="revision" value="main" placeholder="main"/>
          </div>
          <div class="row-full">
            <button type="submit" class="btn btn-hf">Скачать из репозитория</button>
          </div>
        </form>
      </div>
    </div>

    <div id="installed-panel" class="tab-content">
      <div class="card">
        <h3>Установленные .gguf</h3>
        <p style="color:var(--muted); font-size:14px;">Активная модель подхватывается llama-server; OpenClaw синхронизируется (провайдер <span class="mono">local-llama</span>).</p>
        <button type="button" class="btn" style="margin-bottom:12px;" onclick="refreshInstalled()">Обновить список</button>
        <div id="installed-list">Загрузка…</div>
      </div>
    </div>
  </div>

  <script>
const tok = {tok_js};
const jobFromUrl = {job_js};
const noticeFromUrl = {notice_js};

function switchTab(name) {{
  document.querySelectorAll('.wrap > .tabs .tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));
  const tabs = document.querySelectorAll('.wrap > .tabs .tab');
  if (name === 'presets') {{ tabs[0].classList.add('active'); document.getElementById('presets-panel').classList.add('active'); }}
  if (name === 'huggingface') {{ tabs[1].classList.add('active'); document.getElementById('huggingface-panel').classList.add('active'); switchHFMethod('url'); }}
  if (name === 'installed') {{ tabs[2].classList.add('active'); document.getElementById('installed-panel').classList.add('active'); refreshInstalled(); }}
}}

function switchHFMethod(m) {{
  document.querySelectorAll('#huggingface-panel .tabs .tab').forEach(t => t.classList.remove('active'));
  const inner = document.querySelectorAll('#huggingface-panel .tabs .tab');
  if (m === 'url') {{ inner[0].classList.add('active'); document.getElementById('hf-url-form').style.display = 'block'; document.getElementById('hf-repo-form').style.display = 'none'; }}
  else {{ inner[1].classList.add('active'); document.getElementById('hf-url-form').style.display = 'none'; document.getElementById('hf-repo-form').style.display = 'block'; }}
}}

let activeCategory = '__all__';
function filterCategory(btn) {{
  const cat = btn.getAttribute('data-cat') || '__all__';
  activeCategory = cat;
  document.querySelectorAll('.category-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.preset-card').forEach(card => {{
    const c = card.getAttribute('data-category') || '';
    const okCat = cat === '__all__' || c === cat;
    const q = (document.getElementById('preset-search').value || '').toLowerCase();
    const s = (card.getAttribute('data-search') || '').toLowerCase();
    const okSearch = !q || s.includes(q);
    card.classList.toggle('hidden', !(okCat && okSearch));
  }});
}}

function filterPresets() {{
  const q = (document.getElementById('preset-search').value || '').toLowerCase();
  document.querySelectorAll('.preset-card').forEach(card => {{
    const s = (card.getAttribute('data-search') || '').toLowerCase();
    const c = card.getAttribute('data-category') || '';
    const okCat = activeCategory === '__all__' || c === activeCategory;
    const okSearch = !q || s.includes(q);
    card.classList.toggle('hidden', !(okCat && okSearch));
  }});
}}

async function refreshInstalled() {{
  const el = document.getElementById('installed-list');
  const q = tok ? ('?token=' + encodeURIComponent(tok)) : '';
  const r = await fetch('/api/models' + q);
  if (!r.ok) {{ el.innerHTML = '<p class="hint">Нет доступа к API. Укажите <code>?token=</code> в URL.</p>'; return; }}
  const j = await r.json();
  if (!j.models.length) {{ el.innerHTML = '<p style="color:var(--muted)">Нет файлов .gguf — скачайте из пресетов или HuggingFace.</p>'; return; }}
  let h = '<table class="data"><thead><tr><th>Файл</th><th>Размер</th><th></th></tr></thead><tbody>';
  for (const m of j.models) {{
    const mb = (m.bytes/1024/1024).toFixed(0);
    h += '<tr><td>' + escapeHtml(m.name) + (m.active ? ' <strong>(активна)</strong>' : '') + '</td><td>' + mb + ' MB</td><td style="white-space:nowrap">';
    h += '<form method="post" action="/ui/activate" style="display:inline-block;margin-right:8px;"><input type="hidden" name="token" value="'+escapeAttr(tok)+'"/><input type="hidden" name="path" value="'+escapeAttr(m.path)+'"/><button type="submit" class="btn btn-preset" style="width:auto;padding:8px 14px;">Активировать</button></form>';
    h += '<form method="post" action="/ui/delete" style="display:inline-block" onsubmit="return confirm(\\'Удалить файл с диска?\\');"><input type="hidden" name="token" value="'+escapeAttr(tok)+'"/><input type="hidden" name="name" value="'+escapeAttr(m.name)+'"/><button type="submit" class="btn btn-danger" style="width:auto;padding:8px 14px;">Удалить</button></form>';
    h += '</td></tr>';
  }}
  h += '</tbody></table>';
  el.innerHTML = h;
}}

function escapeHtml(s) {{
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}}
function escapeAttr(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
}}

function showBanner(text, isErr) {{
  const slot = document.getElementById('banner-slot');
  if (!text) {{ slot.innerHTML = ''; return; }}
  slot.innerHTML = '<div class="banner' + (isErr ? ' err' : '') + '">' + text + '</div>';
}}

async function pollJob(id) {{
  const q = tok ? ('?token=' + encodeURIComponent(tok)) : '';
  const r = await fetch('/api/downloads/' + id + q);
  const j = await r.json();
  if (j.status === 'done') return showBanner('Загрузка завершена: ' + (j.path || 'ok'), false);
  if (j.status === 'error') return showBanner('Ошибка: ' + (j.error || 'unknown'), true);
  const pct = j.total ? Math.round(100 * j.downloaded / j.total) : 0;
  showBanner('Загрузка… ' + pct + '% (' + (j.downloaded||0) + ' / ' + (j.total||'?') + ' байт)', false);
  setTimeout(() => pollJob(id), 1200);
}}

if (noticeFromUrl) showBanner(noticeFromUrl, false);
if (jobFromUrl) pollJob(jobFromUrl);

setInterval(() => {{
  if (document.getElementById('installed-panel').classList.contains('active')) refreshInstalled();
}}, 10000);
  </script>
</body>
</html>"""


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
            _downloads[job_id] = {"status": "error", "error": "Нужен файл .gguf"}
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
def ui(
    request: Request,
    token: Optional[str] = Query(None),
    job: Optional[str] = Query(None),
    notice: Optional[str] = Query(None),
) -> HTMLResponse:
    _check_token(request, token)
    if _hub_token() and not token:
        return HTMLResponse(
            "<!DOCTYPE html><html><body style='background:#1e1e1e;color:#fff;font-family:sans-serif;padding:40px;'>"
            "<p>Укажите токен в URL: <code>/?token=...</code> (переменная <code>GUILDCLAW_HUB_TOKEN</code>)</p></body></html>",
            status_code=401,
        )
    html_out = _render_index(token, job, notice)
    return HTMLResponse(html_out)


@app.post("/ui/download-preset")
async def ui_dl_preset(
    request: Request,
    url: str = Form(...),
    filename: Optional[str] = Form(None),
    token: Optional[str] = Form(None),
) -> RedirectResponse:
    _check_token(request, token)
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_download_thread, args=(job_id, url, filename), daemon=True).start()
    return _redirect_home(token or "", job=job_id)


@app.post("/ui/download-url")
async def ui_dl_url(
    request: Request,
    url: str = Form(...),
    filename: Optional[str] = Form(None),
    token: Optional[str] = Form(None),
) -> RedirectResponse:
    _check_token(request, token)
    fn = (filename or "").strip() or None
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_download_thread, args=(job_id, url.strip(), fn), daemon=True).start()
    return _redirect_home(token or "", job=job_id)


@app.post("/ui/download-hf-repo")
async def ui_dl_hf_repo(
    request: Request,
    repo: str = Form(...),
    filename: str = Form(...),
    revision: Optional[str] = Form(None),
    token: Optional[str] = Form(None),
) -> RedirectResponse:
    _check_token(request, token)
    repo = repo.strip().strip("/")
    if not _REPO_RE.match(repo):
        raise HTTPException(400, "Репозиторий в формате organization/name")
    filename = filename.strip()
    if not filename.lower().endswith(".gguf"):
        raise HTTPException(400, "Укажите имя файла .gguf")
    url = _hf_resolve_url(repo, filename, revision or "main")
    job_id = uuid.uuid4().hex[:12]
    threading.Thread(target=_download_thread, args=(job_id, url, filename), daemon=True).start()
    return _redirect_home(token or "", job=job_id)


@app.post("/ui/activate")
async def ui_activate(
    request: Request,
    path: str = Form(...),
    token: Optional[str] = Form(None),
) -> RedirectResponse:
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
    return _redirect_home(token or "", notice="Модель активирована, llama-server перезапускается.")


@app.post("/ui/delete")
async def ui_delete(
    request: Request,
    name: str = Form(...),
    token: Optional[str] = Form(None),
) -> RedirectResponse:
    _check_token(request, token)
    p = (GGUF_DIR / name).resolve()
    if str(p).startswith(str(GGUF_DIR.resolve())) and p.is_file():
        if _is_active_path(str(p)):
            ACTIVE_FILE.unlink(missing_ok=True)
        p.unlink()
        _restart_llama()
        _sync_openclaw()
    return _redirect_home(token or "", notice="Файл удалён.")
