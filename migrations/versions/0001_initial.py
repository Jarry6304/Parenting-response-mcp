"""L0 初始 schema:sessions / rounds / records(spec v2.2 資料模型 + 縫補 + 合成v3 連動)。

Revision ID: 0001
Revises:
"""
from __future__ import annotations

from alembic import op

from parenting_response.db import DDL

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS records; DROP TABLE IF EXISTS rounds; DROP TABLE IF EXISTS sessions;")
