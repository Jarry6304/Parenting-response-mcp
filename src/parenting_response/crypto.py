"""信封加密(v3.0 J 件):自由文本欄位 AES-256-GCM,金鑰只在 env(Secret Manager)。

威脅模型:Neon 雲庫外洩 / 備份檔外流時,自由文本(facts/draft/逐字稿/報告)
不可讀。**G0 掃描在 orchestrator 層(加密前)**,db 層透明加解密——
應用拿到的永遠是明文,庫裡躺的永遠是密文。

密文格式:`enc:<key_id>:<nonce_b64>:<ct_b64>`(key_id 進欄位 → 輪替時
新舊金鑰共存可解;nonce 96-bit 隨機,GCM tag 隨 ct)。
未設 ENVELOPE_KEYS → from_env() 回 None = 明文直通(local dev / 測試)。
decrypt 對無前綴值回原文(混存相容:0007 遷移途中/歷史明文不炸)。
"""

from __future__ import annotations

import base64
import json
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "enc:"


class Envelope:
    def __init__(self, keys: dict[str, bytes], active_key_id: str) -> None:
        if active_key_id not in keys:
            raise ValueError(f"ENVELOPE_ACTIVE_KEY_ID={active_key_id} 不在 ENVELOPE_KEYS")
        for kid, key in keys.items():
            if len(key) != 32:
                raise ValueError(f"金鑰 {kid} 須 32 bytes(AES-256);得 {len(key)}")
        self._keys = dict(keys)
        self._active = active_key_id

    @classmethod
    def from_env(cls) -> Envelope | None:
        """ENVELOPE_KEYS(JSON {key_id: b64-32B})+ ENVELOPE_ACTIVE_KEY_ID;
        未設 → None(明文直通)。設了但格式錯 → raise(半開加密比沒加密更危險)。"""
        raw = os.environ.get("ENVELOPE_KEYS")
        if not raw:
            return None
        parsed: dict[str, str] = json.loads(raw)
        keys = {kid: base64.b64decode(b64) for kid, b64 in parsed.items()}
        active = os.environ.get("ENVELOPE_ACTIVE_KEY_ID")
        if not active:
            raise ValueError("設了 ENVELOPE_KEYS 必須同時設 ENVELOPE_ACTIVE_KEY_ID")
        return cls(keys, active)

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._keys[self._active]).encrypt(nonce, plaintext.encode("utf-8"), None)
        return (f"{_PREFIX}{self._active}:"
                f"{base64.b64encode(nonce).decode()}:{base64.b64encode(ct).decode()}")

    def decrypt(self, value: str) -> str:
        if not value.startswith(_PREFIX):
            return value  # 歷史明文/遷移途中混存:照回,不炸
        kid, nonce_b64, ct_b64 = value[len(_PREFIX):].split(":", 2)
        key = self._keys.get(kid)
        if key is None:
            raise ValueError(f"密文 key_id={kid} 不在 ENVELOPE_KEYS(輪替時舊鑰不可先撤)")
        pt = AESGCM(key).decrypt(
            base64.b64decode(nonce_b64), base64.b64decode(ct_b64), None)
        return pt.decode("utf-8")
