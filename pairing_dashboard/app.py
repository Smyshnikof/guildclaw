"""
Pairing dashboard: FastAPI на :8081, вызовы node.pair.* через gateway_client.
"""
from __future__ import annotations

import html
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import gateway_client

app = FastAPI(title="Guildclaw Pairing Dashboard", docs_url=None, redoc_url=None)

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@app.exception_handler(HTTPException)
async def _pairing_http_exception(request: Request, exc: HTTPException) -> Any:
    if exc.status_code == 401:
        body = (
            "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\"/><title>401</title>"
            "<style>body{font-family:system-ui;background:#1a1a1a;color:#e8e8e8;padding:24px}"
            "code{color:#9cf}</style></head><body>"
            f"<h1>Нужен токен</h1><p>{html.escape(str(exc.detail))}</p>"
            "<p>Укажите <code>?token=…</code> в URL или заголовок "
            "<code>Authorization: Bearer …</code> (секрет из <code>GUILDCLAW_PAIRING_DASH_TOKEN</code> "
            "или <code>OPENCLAW_WEB_PASSWORD</code>).</p></body></html>"
        )
        return HTMLResponse(content=body, status_code=401)
    return await http_exception_handler(request, exc)

_PAIRING_TTL_MS = 5 * 60 * 1000


def _dash_secret() -> str:
    dash = (os.environ.get("GUILDCLAW_PAIRING_DASH_TOKEN") or "").strip()
    if dash:
        return dash
    return (os.environ.get("OPENCLAW_WEB_PASSWORD") or os.environ.get("A2GO_AUTH_TOKEN") or "").strip()


def _token_from_request(request: Request) -> Optional[str]:
    q = request.query_params.get("token")
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        q = auth[7:].strip() or q
    return q


def _check_dash(request: Request, form_token: Optional[str] = None) -> None:
    expected = _dash_secret()
    if not expected:
        return
    if _token_from_request(request) == expected:
        return
    if form_token is not None and form_token == expected:
        return
    raise HTTPException(
        status_code=401,
        detail="Нужен токен дашборда: заголовок Authorization: Bearer, query ?token= или поле формы token "
        "(GUILDCLAW_PAIRING_DASH_TOKEN или OPENCLAW_WEB_PASSWORD).",
    )


def _hidden_token(request: Request) -> str:
    t = _token_from_request(request) or ""
    exp = _dash_secret()
    if exp and t == exp:
        return t
    return ""


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    _check_dash(request, None)
    err: Optional[str] = None
    data: dict[str, Any] = {"pending": [], "paired": []}
    try:
        raw = await gateway_client.pair_list()
        if isinstance(raw, dict):
            data["pending"] = raw.get("pending") or []
            data["paired"] = raw.get("paired") or []
    except Exception as e:
        err = str(e)

    now_ms = int(time.time() * 1000)
    return _TEMPLATES.TemplateResponse(
        request,
        "pairing.html",
        {
            "pending": data["pending"],
            "paired": data["paired"],
            "error": err,
            "auth_token": _hidden_token(request),
            "dash_secret_configured": bool(_dash_secret()),
            "now_ms": now_ms,
            "ttl_ms": _PAIRING_TTL_MS,
        },
    )


@app.post("/approve", response_class=HTMLResponse)
async def approve(
    request: Request,
    request_id: str = Form(...),
    token: str = Form(""),
) -> Any:
    _check_dash(request, token.strip() or None)
    try:
        await gateway_client.pair_approve(request_id)
    except Exception as e:
        ht = _hidden_token(request)
        back = "/?token=" + quote(ht, safe="") if ht else "/"
        return _TEMPLATES.TemplateResponse(
            request,
            "pairing_message.html",
            {"title": "Ошибка", "message": str(e), "back_url": back},
            status_code=200,
        )
    q = "?token=" + quote(token.strip(), safe="") if token.strip() and _dash_secret() == token.strip() else ""
    return RedirectResponse(url="/" + q, status_code=303)


@app.post("/reject", response_class=HTMLResponse)
async def reject(
    request: Request,
    request_id: str = Form(...),
    token: str = Form(""),
) -> Any:
    _check_dash(request, token.strip() or None)
    try:
        await gateway_client.pair_reject(request_id)
    except Exception as e:
        ht = _hidden_token(request)
        back = "/?token=" + quote(ht, safe="") if ht else "/"
        return _TEMPLATES.TemplateResponse(
            request,
            "pairing_message.html",
            {"title": "Ошибка", "message": str(e), "back_url": back},
            status_code=200,
        )
    q = "?token=" + quote(token.strip(), safe="") if token.strip() and _dash_secret() == token.strip() else ""
    return RedirectResponse(url="/" + q, status_code=303)
