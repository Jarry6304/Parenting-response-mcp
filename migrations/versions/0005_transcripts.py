"""raw_transcripts 原始逐字稿表(spec v3.0 E 件;append-only side-table)。

turns 存 JSON 文字(TEXT,0007 就地加密就緒);UNIQUE(session_id, content_hash)
承載 chunk 冪等。不動 records schema_version(side-table 與 events 同理)。

冪等:0001 動態 import 現行 DDL(已含本表),全新庫在 0001 即得,本檔須可 no-op;
CREATE 塊與 db.ensure_schema() 共用 db.DDL_TRANSCRIPTS(單一來源)。

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL_TRANSCRIPTS

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL_TRANSCRIPTS)


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS raw_transcripts_session_idx;"
        "DROP TABLE IF EXISTS raw_transcripts;"
    )
