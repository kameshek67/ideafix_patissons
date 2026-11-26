"""passages

Справочные фрагменты для поиска помощника: правила приёма, карточки олимпиад, документы вузов,
материалы олимпиад. Таблица входит в DATA_TABLES: olymp-ingest очищает и заново наполняет её.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT = sa.Text(collation="C")
EMPTY = sa.text("''")


def upgrade() -> None:
    op.create_table(
        "passages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", TEXT, nullable=False),
        sa.Column("title", TEXT, nullable=False),
        sa.Column("url", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("page", sa.SmallInteger(), nullable=True),
        sa.Column("chunk", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("body", TEXT, nullable=False),
        sa.Column("document", postgresql.TSVECTOR(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('university_document', 'olympiad_card', 'admission_rule',"
            " 'olympiad_material')",
            name=op.f("ck_passages_source_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_passages")),
    )
    op.create_index(op.f("ix_passages_document"), "passages", ["document"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index(op.f("ix_passages_document"), table_name="passages", postgresql_using="gin")
    op.drop_table("passages")
