"""benefit ege columns

Разобранный порог ЕГЭ строки льготы (F-03, T-031): коды предметов и число. Заполняет
olymp-ingest; до пересборки колонки пустые.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "benefits",
        sa.Column("confirm_subjects", postgresql.ARRAY(sa.Text(collation="C")), nullable=True),
    )
    op.add_column("benefits", sa.Column("min_ege_score", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("benefits", "min_ege_score")
    op.drop_column("benefits", "confirm_subjects")
