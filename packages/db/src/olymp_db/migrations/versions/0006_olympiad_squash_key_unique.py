"""olympiads.squash_key unique

По squash_key дипломы пользователей и ссылки «Поделиться» находят олимпиаду после пересборки.
Два одинаковых ключа сделали бы выбор случайным — пусть лучше упадёт сборка (T-075).

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_olympiads_squash_key", "olympiads", ["squash_key"])


def downgrade() -> None:
    op.drop_constraint("uq_olympiads_squash_key", "olympiads", type_="unique")
