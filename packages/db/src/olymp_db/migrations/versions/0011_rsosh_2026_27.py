"""rsosh 2026/27

Перечень олимпиад РСОШ на 2026/27 (data/rsosh_2026_27.json): у олимпиады признак «в перечне»,
у профиля — уровень по новому перечню. Заполняет olymp-ingest; до пересборки колонки пустые.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("olympiads", sa.Column("in_rsosh_2026_27", sa.Boolean(), nullable=True))
    op.add_column(
        "olympiad_profiles",
        sa.Column(
            "level_2026_27", sa.Text(collation="C"), server_default=sa.text("''"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("olympiad_profiles", "level_2026_27")
    op.drop_column("olympiads", "in_rsosh_2026_27")
