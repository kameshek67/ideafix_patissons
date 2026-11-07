"""share links

Снимки для ссылок «Поделиться» (F-01). Таблица не входит в DATA_TABLES и не ссылается на
таблицы сборки: пересборка базы (olymp-ingest) её не очищает, а ключи в снимке — squash
названий, поэтому ссылка открывает тот же экран и после пересборки.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "share_links",
        sa.Column("token", sa.Text(collation="C"), nullable=False),
        sa.Column("kind", sa.Text(collation="C"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.Text(collation="C"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_opened", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('program', 'olympiad', 'diplomas')", name=op.f("ck_share_links_kind")
        ),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_share_links")),
        sa.UniqueConstraint("payload_hash", name=op.f("uq_share_links_payload_hash")),
    )
    op.create_index(op.f("ix_share_links_expires_at"), "share_links", ["expires_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_share_links_expires_at"), table_name="share_links")
    op.drop_table("share_links")
