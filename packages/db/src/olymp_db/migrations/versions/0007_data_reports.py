"""data reports

Сообщения «Нашли ошибку в данных» (T-079). Таблица не входит в DATA_TABLES и не ссылается
внешними ключами на таблицы сборки: пересборка базы её не трогает.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.Text(collation="C"), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=True),
        sa.Column("olympiad_id", sa.Integer(), nullable=True),
        sa.Column("university_id", sa.Integer(), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message", sa.Text(collation="C"), nullable=False),
        sa.Column(
            "status", sa.Text(collation="C"), server_default=sa.text("'new'"), nullable=False
        ),
        sa.CheckConstraint("kind IN ('program', 'olympiad')", name=op.f("ck_data_reports_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_reports")),
    )
    op.create_index(op.f("ix_data_reports_created_at"), "data_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_data_reports_created_at"), table_name="data_reports")
    op.drop_table("data_reports")
