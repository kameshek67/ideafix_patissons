"""sources and source_jobs

Источники (страница или документ вуза) и задачи их разбора: ссылка от оператора →
скачать → извлечь → проверить цитаты → разница с базой → принять или отклонить.
Таблицы не входят в DATA_TABLES: пересборка их не стирает.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT = sa.Text(collation="C")
EMPTY = sa.text("''")
NOW = sa.func.now()


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("university", TEXT, nullable=False),
        sa.Column("url", TEXT, nullable=False),
        sa.Column("kind", TEXT, server_default=sa.text("'page'"), nullable=False),
        sa.Column("added_by", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sha256", TEXT, server_default=EMPTY, nullable=False),
        sa.CheckConstraint("kind IN ('page', 'document')", name=op.f("ck_sources_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("url", name=op.f("uq_sources_url")),
    )
    op.create_table(
        "source_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("status", TEXT, server_default=sa.text("'queued'"), nullable=False),
        sa.Column("error", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("documents", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("records_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("quotes_checked", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("quotes_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("diff", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        # извлечённые файлы (extraction.ExtractionFile) — то, что принимает accept
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("rebuild_needed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rebuilt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'fetching', 'extracting', 'review', 'accepted', 'rejected',"
            " 'failed')",
            name=op.f("ck_source_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_source_jobs_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_jobs")),
    )
    op.create_index(op.f("ix_source_jobs_status"), "source_jobs", ["status"])
    op.create_index(op.f("ix_source_jobs_source_id"), "source_jobs", ["source_id"])


def downgrade() -> None:
    op.drop_table("source_jobs")
    op.drop_table("sources")
