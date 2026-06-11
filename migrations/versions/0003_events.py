"""events 稽核事件表(defect-fixes #7/#8):G0 命中與 ④ 拒收落庫,證據鏈可重建。

冪等:0001 動態 import 現行 DDL(已含 events),全新庫在 0001 即得本表,本檔須可 no-op;
CREATE 塊與 db.ensure_schema() 共用 db.DDL_EVENTS(單一來源)。

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL_EVENTS

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL_EVENTS)


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS events_session_idx;"
        "DROP TABLE IF EXISTS events;"
    )
