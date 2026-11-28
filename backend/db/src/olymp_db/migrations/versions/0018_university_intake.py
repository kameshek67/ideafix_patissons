"""university_intake: сколько олимпиадников принимают вузы

Данные сводной панели «Мониторинг эффективности вузов» по вузам базы: год, принято
победителей и призёров олимпиад, их доля и средний балл ЕГЭ принятых на бюджет. Таблица входит
в DATA_TABLES: olymp-ingest очищает и заново наполняет её из data/monitoring/olympiad_intake.csv.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "university_intake",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("university_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("olympiad_students", sa.Integer(), nullable=True),
        sa.Column("olympiad_share", sa.Float(), nullable=True),
        sa.Column("avg_score_budget", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "olympiad_students IS NULL OR olympiad_students > 0",
            name=op.f("ck_university_intake_students"),
        ),
        sa.ForeignKeyConstraint(
            ["university_id"],
            ["universities.id"],
            name=op.f("fk_university_intake_university_id_universities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_university_intake")),
        sa.UniqueConstraint(
            "university_id", "year", name=op.f("uq_university_intake_university_id_year")
        ),
    )


def downgrade() -> None:
    op.drop_table("university_intake")
