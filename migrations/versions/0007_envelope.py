"""自由文本就地信封加密(spec v3.0 J 件)。

既有明文列逐欄加密(AES-256-GCM,`enc:<key_id>:…` 格式);**需設
ENVELOPE_KEYS / ENVELOPE_ACTIVE_KEY_ID**,未設即 raise(半加密庫比明文庫
更危險——應用會誤判已保護)。冪等:已有 `enc:` 前綴之值跳過,中斷重跑安全。
欄位清單單一來源 = db.ENCRYPTED_*_FIELDS。

downgrade 即解密回明文(需同一組金鑰)。

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

from parenting_response.crypto import Envelope
from parenting_response.db import (
    ENCRYPTED_RECORD_FIELDS,
    ENCRYPTED_REPORT_FIELDS,
    ENCRYPTED_ROUND_FIELDS,
    ENCRYPTED_SESSION_FIELDS,
    ENCRYPTED_TRANSCRIPT_FIELDS,
)

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# (表, PK 欄序列——rounds 為複合鍵, 加密欄位)
_TABLES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("sessions", ("session_id",), ENCRYPTED_SESSION_FIELDS),
    ("rounds", ("session_id", "round_no"), ENCRYPTED_ROUND_FIELDS),
    ("records", ("record_id",), ENCRYPTED_RECORD_FIELDS),
    ("raw_transcripts", ("transcript_id",), ENCRYPTED_TRANSCRIPT_FIELDS),
    ("reports", ("report_id",), ENCRYPTED_REPORT_FIELDS),
]


def _require_env() -> Envelope:
    env = Envelope.from_env()
    if env is None:
        raise RuntimeError(
            "0007 需 ENVELOPE_KEYS + ENVELOPE_ACTIVE_KEY_ID(就地加密既有資料);"
            "尚未準備金鑰請先停在 0006")
    return env


def _transform(direction: str) -> None:
    env = _require_env()
    conn = op.get_bind()
    for table, pks, fields in _TABLES:
        pk_cols = ", ".join(pks)
        where_pk = " AND ".join(f"{c} = :k{i}" for i, c in enumerate(pks))
        for field in fields:
            cond = (f"{field} IS NOT NULL AND {field} NOT LIKE 'enc:%'"
                    if direction == "encrypt" else f"{field} LIKE 'enc:%'")
            rows = conn.execute(text(
                f"SELECT {pk_cols}, {field} FROM {table} WHERE {cond}"  # noqa: S608(識別字皆來自常數表)
            )).fetchall()
            for row in rows:
                *pk_vals, value = row
                new = (env.encrypt(str(value)) if direction == "encrypt"
                       else env.decrypt(str(value)))
                conn.execute(
                    text(f"UPDATE {table} SET {field} = :v WHERE {where_pk}"),  # noqa: S608
                    {"v": new, **{f"k{i}": pv for i, pv in enumerate(pk_vals)}},
                )


def upgrade() -> None:
    _transform("encrypt")


def downgrade() -> None:
    _transform("decrypt")
