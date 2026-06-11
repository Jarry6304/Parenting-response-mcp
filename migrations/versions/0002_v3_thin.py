"""v3.0 thin server:sessions.stage / records.{claimed_sources,draft} / 鬆 NOT NULL。

冪等:0001 動態 import 現行 DDL,全新庫在 0001 即得 v3 形狀,本檔須可 no-op;
ALTER 塊與 db.ensure_schema() 共用 db.DDL_MIGRATE(單一來源)。

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL_MIGRATE

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL_MIGRATE)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE records DROP COLUMN IF EXISTS draft;"
        "ALTER TABLE records DROP COLUMN IF EXISTS claimed_sources;"
        "ALTER TABLE records ALTER COLUMN schema_version SET DEFAULT 1;"
        "ALTER TABLE sessions DROP COLUMN IF EXISTS stage;"
    )
