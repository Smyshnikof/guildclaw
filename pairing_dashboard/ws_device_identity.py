"""
Ed25519 device identity для WS connect OpenClaw (подпись connect.challenge v3).
Без device шлюз обнуляет self-declared scopes → node.pair.* даёт «missing scope: operator.pairing».
Формат payload: openclaw src/gateway/device-auth.ts buildDeviceAuthPayloadV3.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _norm_meta(value: str | None) -> str:
    """Как normalizeDeviceMetadataForAuth в OpenClaw: trim + только ASCII A–Z → lower."""
    if not value or not isinstance(value, str):
        return ""
    t = value.strip()
    if not t:
        return ""
    out: list[str] = []
    for c in t:
        o = ord(c)
        if 65 <= o <= 90:
            out.append(chr(o + 32))
        else:
            out.append(c)
    return "".join(out)


def _identity_path() -> Path:
    custom = (os.environ.get("GUILDCLAW_PAIRING_DEVICE_JSON") or "").strip()
    if custom:
        return Path(custom)
    base = (os.environ.get("GUILDCLAW_STATE_DIR") or "/workspace/.guildclaw").strip()
    return Path(base) / "pairing_ws_device.json"


@dataclass
class WsDeviceIdentity:
    device_id: str
    public_key_pem: str
    private_key_pem: str


def _fingerprint_device_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def load_or_create_ws_device_identity() -> WsDeviceIdentity:
    path = _identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(raw, dict)
                and raw.get("version") == 1
                and raw.get("deviceId")
                and raw.get("publicKeyPem")
                and raw.get("privateKeyPem")
            ):
                pk = serialization.load_pem_public_key(
                    str(raw["publicKeyPem"]).encode("utf-8")
                )
                if isinstance(pk, Ed25519PublicKey):
                    derived = _fingerprint_device_id(pk)
                    did = str(raw["deviceId"])
                    if derived != did:
                        raw["deviceId"] = derived
                        path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
                        did = derived
                    return WsDeviceIdentity(
                        device_id=did,
                        public_key_pem=str(raw["publicKeyPem"]),
                        private_key_pem=str(raw["privateKeyPem"]),
                    )
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    device_id = _fingerprint_device_id(pub)
    stored: dict[str, Any] = {
        "version": 1,
        "deviceId": device_id,
        "publicKeyPem": pub_pem,
        "privateKeyPem": priv_pem,
        "createdAtMs": int(time.time() * 1000),
    }
    path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return WsDeviceIdentity(
        device_id=device_id,
        public_key_pem=pub_pem,
        private_key_pem=priv_pem,
    )


def build_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str,
    nonce: str,
    platform: str,
    device_family: str,
) -> str:
    scopes_s = ",".join(scopes)
    token_s = token or ""
    plat = _norm_meta(platform)
    fam = _norm_meta(device_family)
    return "|".join(
        [
            "v3",
            device_id,
            client_id,
            client_mode,
            role,
            scopes_s,
            str(signed_at_ms),
            token_s,
            nonce,
            plat,
            fam,
        ]
    )


def sign_payload_v3(private_key_pem: str, payload: str) -> str:
    sk = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"), password=None
    )
    if not isinstance(sk, Ed25519PrivateKey):
        raise TypeError("ожидался Ed25519 private key")
    sig = sk.sign(payload.encode("utf-8"))
    return _b64url(sig)
