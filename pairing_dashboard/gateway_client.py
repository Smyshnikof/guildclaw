"""
WebSocket-клиент к OpenClaw Gateway (JSON-RPC).
Документация: https://github.com/openclaw/openclaw/blob/main/docs/gateway/protocol.md

Оператор с валидным shared token на loopback может не передавать device
(roleCanSkipDeviceIdentity в openclaw role-policy).
Клиент объявляется как cli/cli — как у openclaw CLI в контейнере.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Optional

import websockets
from websockets.client import WebSocketClientProtocol

_OPERATOR_SCOPES = [
    "operator.read",
    "operator.write",
    "operator.pairing",
    "operator.admin",
]


def _gateway_token() -> str:
    t = (os.environ.get("OPENCLAW_GATEWAY_TOKEN") or "").strip()
    if t:
        return t
    return (os.environ.get("OPENCLAW_WEB_PASSWORD") or os.environ.get("A2GO_AUTH_TOKEN") or "").strip()


def _gateway_ws_url() -> str:
    return (os.environ.get("OPENCLAW_GATEWAY_WS") or "ws://127.0.0.1:18789").strip()


async def _recv_until_res(ws: WebSocketClientProtocol, expect_id: str, timeout: float) -> dict[str, Any]:
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("type") == "res" and msg.get("id") == expect_id:
            return msg


async def _drain_connect_challenge(ws: WebSocketClientProtocol, timeout: float) -> None:
    """Сервер шлёт event connect.challenge до первого connect (актуальные версии OpenClaw)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + min(timeout, 5.0)
    while loop.time() < deadline:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "event" and msg.get("event") == "connect.challenge":
            return
        # иные события до connect игнорируем


async def _connect_operator(ws: WebSocketClientProtocol, token: str, timeout: float) -> None:
    await _drain_connect_challenge(ws, timeout)

    conn_id = str(uuid.uuid4())
    payload = {
        "type": "req",
        "id": conn_id,
        "method": "connect",
        "params": {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": "cli",
                "version": "1.0.0",
                "platform": "linux",
                "mode": "cli",
            },
            "role": "operator",
            "scopes": _OPERATOR_SCOPES,
            "caps": [],
            "commands": [],
            "permissions": {},
            "auth": {"token": token},
            "locale": "ru-RU",
            "userAgent": "guildclaw-pairing-dashboard/1.0",
        },
    }
    await ws.send(json.dumps(payload))
    res = await _recv_until_res(ws, conn_id, timeout)
    if not res.get("ok"):
        err = res.get("error") or res
        raise RuntimeError(f"connect failed: {err}")


async def gateway_rpc(
    method: str,
    params: Optional[dict[str, Any]] = None,
    *,
    timeout: float = 30.0,
) -> Any:
    token = _gateway_token()
    if not token:
        raise RuntimeError("Нет токена шлюза: задайте OPENCLAW_WEB_PASSWORD или OPENCLAW_GATEWAY_TOKEN")

    url = _gateway_ws_url()
    params = params or {}

    ws_ctx = websockets.connect(
        url,
        open_timeout=timeout,
        close_timeout=5,
        max_size=10 * 1024 * 1024,
    )
    try:
        async with ws_ctx as ws:
            await _connect_operator(ws, token, timeout)

            rid = str(uuid.uuid4())
            await ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": rid,
                        "method": method,
                        "params": params,
                    }
                )
            )
            res = await _recv_until_res(ws, rid, timeout)
            if not res.get("ok"):
                err = res.get("error") or res
                raise RuntimeError(f"{method}: {err}")
            return res.get("payload")
    except asyncio.TimeoutError as e:
        raise RuntimeError(f"Таймаут шлюза ({url})") from e
    except OSError as e:
        raise RuntimeError(f"Шлюз недоступен ({url}): {e}") from e
    except Exception as e:
        if e.__class__.__module__.startswith("websockets"):
            raise RuntimeError(f"Ошибка WebSocket ({url}): {e}") from e
        raise


async def pair_list() -> Any:
    return await gateway_rpc("node.pair.list", {})


async def pair_approve(request_id: str) -> Any:
    return await gateway_rpc("node.pair.approve", {"requestId": request_id.strip()})


async def pair_reject(request_id: str) -> Any:
    return await gateway_rpc("node.pair.reject", {"requestId": request_id.strip()})
