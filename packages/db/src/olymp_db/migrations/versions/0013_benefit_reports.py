"""benefit reports

Жалоба «Не совпадает с документом» у строки льготы: ключ строки, причина, ссылка, источник
(пользователь, сверщик, мониторинг), статусы проверки и цитата из документа. Таблица, как и
раньше, не входит в DATA_TABLES.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT = sa.Text(collation="C")
EMPTY = sa.text("''")


def upgrade() -> None:
    for column in (
        sa.Column("row_key", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("reason", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("link", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("source", TEXT, server_default=sa.text("'user'"), nullable=False),
        sa.Column("max_user_id", sa.BigInteger(), nullable=True),
        sa.Column("quote", TEXT, server_default=EMPTY, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_notified_status", TEXT, server_default=EMPTY, nullable=False),
    ):
        op.add_column("data_reports", column)

    # жалобы, принятые до этой миграции, оператору уже не рассылаем
    op.execute("UPDATE data_reports SET operator_notified_at = now()")

    op.drop_constraint(op.f("ck_data_reports_kind"), "data_reports", type_="check")
    op.create_check_constraint(
        op.f("ck_data_reports_kind"),
        "data_reports",
        "kind IN ('program', 'olympiad', 'benefit')",
    )
    op.create_check_constraint(
        op.f("ck_data_reports_status"),
        "data_reports",
        "status IN ('new', 'seen', 'checking', 'fixed', 'correct', 'duplicate')",
    )
    op.create_check_constraint(
        op.f("ck_data_reports_source"), "data_reports", "source IN ('user', 'verifier', 'monitor')"
    )
    op.create_check_constraint(
        op.f("ck_data_reports_correct_quote"),
        "data_reports",
        "status <> 'correct' OR (quote IS NOT NULL AND quote <> '')",
    )
    op.create_index(op.f("ix_data_reports_row_key"), "data_reports", ["row_key"])
    op.create_index(op.f("ix_data_reports_status"), "data_reports", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_data_reports_status"), table_name="data_reports")
    op.drop_index(op.f("ix_data_reports_row_key"), table_name="data_reports")
    for name in ("correct_quote", "source", "status"):
        op.drop_constraint(op.f(f"ck_data_reports_{name}"), "data_reports", type_="check")
    op.execute("DELETE FROM data_reports WHERE kind = 'benefit'")
    op.drop_constraint(op.f("ck_data_reports_kind"), "data_reports", type_="check")
    op.create_check_constraint(
        op.f("ck_data_reports_kind"), "data_reports", "kind IN ('program', 'olympiad')"
    )
    for column in (
        "user_notified_status",
        "operator_notified_at",
        "resolved_at",
        "quote",
        "max_user_id",
        "source",
        "link",
        "reason",
        "row_key",
    ):
        op.drop_column("data_reports", column)
