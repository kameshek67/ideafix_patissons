"""document records

Записи о льготах, извлечённые из документов вузов и принятые оператором: таблица
document_records не входит в DATA_TABLES, пересборка её не стирает. В benefits — слой
document и поля источника: страница документа и цитата.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT = sa.Text(collation="C")
EMPTY = sa.text("''")


def upgrade() -> None:
    op.create_table(
        "document_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_url", TEXT, nullable=False),
        sa.Column("document_sha256", TEXT, nullable=False),
        sa.Column("document_title", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("university", TEXT, nullable=False),
        sa.Column("campaign", sa.SmallInteger(), nullable=False),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("accepted_by", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("origin", TEXT, server_default=sa.text("'operator'"), nullable=False),
        sa.CheckConstraint(
            "origin IN ('file', 'operator')", name=op.f("ck_document_records_origin")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_records")),
    )
    op.create_index(op.f("ix_document_records_document_url"), "document_records", ["document_url"])

    op.add_column("benefits", sa.Column("source_page", sa.SmallInteger(), nullable=True))
    op.add_column("benefits", sa.Column("source_quote", TEXT, server_default=EMPTY, nullable=False))
    op.drop_constraint(op.f("ck_benefits_layer"), "benefits", type_="check")
    op.create_check_constraint(
        op.f("ck_benefits_layer"),
        "benefits",
        "layer IN ('summary', 'detailed', 'derived', 'raw', 'document')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM benefits WHERE layer = 'document'")
    op.drop_constraint(op.f("ck_benefits_layer"), "benefits", type_="check")
    op.create_check_constraint(
        op.f("ck_benefits_layer"),
        "benefits",
        "layer IN ('summary', 'detailed', 'derived', 'raw')",
    )
    op.drop_column("benefits", "source_quote")
    op.drop_column("benefits", "source_page")
    op.drop_index(op.f("ix_document_records_document_url"), table_name="document_records")
    op.drop_table("document_records")
