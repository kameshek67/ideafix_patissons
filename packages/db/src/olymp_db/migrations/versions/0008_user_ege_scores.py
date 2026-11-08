"""user ege scores

Баллы ЕГЭ в профиле ученика MAX (F-03, T-032). Не таблица сборки; удаляются вместе
с пользователем.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_ege_scores",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.Text(collation="C"), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_user_ege_scores_score")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["max_users.id"],
            name=op.f("fk_user_ege_scores_user_id_max_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "subject", name=op.f("pk_user_ege_scores")),
    )


def downgrade() -> None:
    op.drop_table("user_ege_scores")
