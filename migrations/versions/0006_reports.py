"""reports 報告定稿表 + events.session_id 放寬可空(spec v3.2 F/H 件)。

reports:同 ref 多版 version 遞增(UNIQUE(scope, ref_key, version)),body 為
確定性組裝全文(TEXT,0007 加密就緒),meta 存聚合快照/slots/語意警示
(季報回放讀上一季 meta)。報告級事件(report_audit/report_semantic_warning/
report_rejected)無 session 錨 → events.session_id DROP NOT NULL,payload 帶
ref_key。append-only side-table,不動 records schema_version。

冪等:0001 動態 import 現行 DDL(已含 reports、events 已無 NOT NULL),
本檔須可 no-op;與 db.ensure_schema() 共用 db.DDL_REPORTS / DDL_MIGRATE_0006。

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL_MIGRATE_0006, DDL_REPORTS

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL_REPORTS)
    op.execute(DDL_MIGRATE_0006)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS reports;"
        "DELETE FROM events WHERE session_id IS NULL;"
        "ALTER TABLE events ALTER COLUMN session_id SET NOT NULL;"
    )
