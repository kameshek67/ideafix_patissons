"""benefit row_key

Стабильный ключ строки льготы: хэш смысловых полей (см. olymp_workers.row_keys). В отличие
от id не сдвигается при правках разбора. Заполняет olymp-ingest; до пересборки колонка пустая.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "benefits",
        sa.Column("row_key", sa.Text(collation="C"), server_default=sa.text("''"), nullable=False),
    )
    op.create_index(op.f("ix_benefits_row_key"), "benefits", ["row_key"])


def downgrade() -> None:
    op.drop_index(op.f("ix_benefits_row_key"), table_name="benefits")
    op.drop_column("benefits", "row_key")
