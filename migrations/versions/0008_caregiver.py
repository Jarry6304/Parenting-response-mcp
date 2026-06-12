"""sessions.caregiver 多照顧者欄(spec v3.0 K 件)。

caregiver ∈ 爸|媽,由已驗 sub 經 CAREGIVER_MAP 映射(不收輸入參數);
既有列回填 DEFAULT '爸'(單人時期的事實)。報告聚合僅「自照」計數,
不產對比節;比較句進語意 tripwire。

冪等:0001 動態 import 現行 DDL(已含本欄),本檔須可 no-op;
ALTER 塊與 db.ensure_schema() 共用 db.DDL_MIGRATE_0008(單一來源)。

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL_MIGRATE_0008

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL_MIGRATE_0008)


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS caregiver;")
