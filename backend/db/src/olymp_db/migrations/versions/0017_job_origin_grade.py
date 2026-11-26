"""source_jobs: откуда задача, оценка автопроверки, id пользователя MAX

Задачу ставит оператор или посетитель сайта («Предложить вуз или документ»). Автопроверка
конвейера кладёт оценку green / yellow / red и причины; пользователю из MAX бот отвечает после
решения оператора.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT = sa.Text(collation="C")
EMPTY = sa.text("''")


def upgrade() -> None:
    op.add_column(
        "source_jobs",
        sa.Column("origin", TEXT, server_default=sa.text("'operator'"), nullable=False),
    )
    op.add_column("source_jobs", sa.Column("comment", TEXT, server_default=EMPTY, nullable=False))
    op.add_column("source_jobs", sa.Column("max_user_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "source_jobs", sa.Column("user_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("source_jobs", sa.Column("grade", TEXT, server_default=EMPTY, nullable=False))
    op.add_column(
        "source_jobs",
        sa.Column(
            "grade_reasons", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_source_jobs_origin"), "source_jobs", "origin IN ('operator', 'user')"
    )
    op.create_check_constraint(
        op.f("ck_source_jobs_grade"), "source_jobs", "grade IN ('', 'green', 'yellow', 'red')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_source_jobs_grade"), "source_jobs")
    op.drop_constraint(op.f("ck_source_jobs_origin"), "source_jobs")
    for column in (
        "grade_reasons",
        "grade",
        "user_notified_at",
        "max_user_id",
        "comment",
        "origin",
    ):
        op.drop_column("source_jobs", column)
