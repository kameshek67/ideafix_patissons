"""individual achievements

Баллы вузов за индивидуальные достижения (ГТО, аттестат с отличием, спорт…) и потолок
суммы. Таблицы входят в DATA_TABLES: olymp-ingest очищает и заново наполняет их из
data/individual_achievements*.csv.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY = sa.text("''")


def _text(name: str) -> sa.Column[str]:
    return sa.Column(name, sa.Text(collation="C"), server_default=_EMPTY, nullable=False)


def upgrade() -> None:
    op.create_table(
        "individual_achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_key", sa.Text(collation="C"), nullable=False),
        sa.Column("university_id", sa.Integer(), nullable=False),
        sa.Column("admission_year", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Text(collation="C"), nullable=False),
        sa.Column(
            "variants",
            postgresql.ARRAY(sa.Text(collation="C")),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("points", sa.SmallInteger(), nullable=False),
        sa.Column(
            "years",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("recency_years", sa.SmallInteger(), nullable=True),
        _text("exclusive_group"),
        _text("label"),
        _text("notes"),
        _text("source_url"),
        sa.Column("source_page", sa.SmallInteger(), nullable=True),
        _text("source_quote"),
        sa.Column(
            "review", sa.Text(collation="C"), server_default=sa.text("'extracted'"), nullable=False
        ),
        sa.CheckConstraint("points >= 0", name=op.f("ck_individual_achievements_points")),
        sa.CheckConstraint(
            "review IN ('extracted', 'reviewed')", name=op.f("ck_individual_achievements_review")
        ),
        sa.ForeignKeyConstraint(
            ["university_id"],
            ["universities.id"],
            name=op.f("fk_individual_achievements_university_id_universities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_individual_achievements")),
        sa.UniqueConstraint("rule_key", name=op.f("uq_individual_achievements_rule_key")),
    )
    op.create_index(
        op.f("ix_individual_achievements_university_id_admission_year"),
        "individual_achievements",
        ["university_id", "admission_year"],
    )
    op.create_table(
        "individual_achievement_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("university_id", sa.Integer(), nullable=False),
        sa.Column("admission_year", sa.SmallInteger(), nullable=False),
        sa.Column("max_total", sa.SmallInteger(), nullable=False),
        _text("source_url"),
        sa.Column("source_page", sa.SmallInteger(), nullable=True),
        _text("source_quote"),
        sa.Column(
            "review", sa.Text(collation="C"), server_default=sa.text("'extracted'"), nullable=False
        ),
        sa.CheckConstraint(
            "max_total >= 0", name=op.f("ck_individual_achievement_limits_max_total")
        ),
        sa.ForeignKeyConstraint(
            ["university_id"],
            ["universities.id"],
            name=op.f("fk_individual_achievement_limits_university_id_universities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_individual_achievement_limits")),
        sa.UniqueConstraint(
            "university_id",
            "admission_year",
            name=op.f("uq_individual_achievement_limits_university_id_admission_year"),
        ),
    )


def downgrade() -> None:
    op.drop_table("individual_achievement_limits")
    op.drop_index(
        op.f("ix_individual_achievements_university_id_admission_year"),
        table_name="individual_achievements",
    )
    op.drop_table("individual_achievements")
