"""v3.2 G0 訊號欄(spec v3.2 A 件 + B/C 件連動欄位;record-schema schema_version 2→3)。

sessions:redflag_active / redflag_vector(A 件,G0 閘→訊號)、parent_action(B 件
retro 暫存)、updated_at(C 件 resume TTL 續期錨,回填 = created_at)。
records:redflag(A 件,promotion 排除錨)、parent_action(B 件);schema_version
DEFAULT 2→3(欄位變更必 bump,歸 record-schema.md 版本管理)。

legacy:既有 redflag_stopped sessions 保留原值(歷史終態,查詢視同 closed);
既有 records.status='stopped' 保留;promotion 守衛同時排除 stopped 與
redflag=true(雙保險)。

冪等:0001 動態 import 現行 DDL,全新庫在 0001 即得 v3.2 形狀,本檔須可 no-op;
ALTER 塊與 db.ensure_schema() 共用 db.DDL_MIGRATE_0004(單一來源)。

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL_MIGRATE_0004

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL_MIGRATE_0004)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE records DROP COLUMN IF EXISTS parent_action;"
        "ALTER TABLE records DROP COLUMN IF EXISTS redflag;"
        "ALTER TABLE records ALTER COLUMN schema_version SET DEFAULT 2;"
        "ALTER TABLE sessions DROP COLUMN IF EXISTS updated_at;"
        "ALTER TABLE sessions DROP COLUMN IF EXISTS parent_action;"
        "ALTER TABLE sessions DROP COLUMN IF EXISTS redflag_vector;"
        "ALTER TABLE sessions DROP COLUMN IF EXISTS redflag_active;"
    )
