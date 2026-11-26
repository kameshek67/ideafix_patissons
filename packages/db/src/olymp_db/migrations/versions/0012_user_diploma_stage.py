"""user diploma stage

Этап ВсОШ в дипломе ученика: f — заключительный, r — региональный. Прежние дипломы —
заключительный этап.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_diplomas",
        sa.Column("stage", sa.Text(collation="C"), server_default=sa.text("'f'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_user_diplomas_stage"), "user_diplomas", "stage IN ('f', 'r')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_user_diplomas_stage"), "user_diplomas", type_="check")
    op.drop_column("user_diplomas", "stage")
