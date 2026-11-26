"""olympiad cards

Карточки олимпиад и их треки. Таблицы входят в DATA_TABLES: olymp-ingest очищает и заново
наполняет их из data/olympiad_cards.json.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY = sa.text("''")
_NO_ITEMS = sa.text("'{}'")


def _text(name: str) -> sa.Column[str]:
    return sa.Column(name, sa.Text(collation="C"), server_default=_EMPTY, nullable=False)


def _list(name: str) -> sa.Column[list[str]]:
    return sa.Column(
        name,
        postgresql.ARRAY(sa.Text(collation="C")),
        server_default=_NO_ITEMS,
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "olympiad_info",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("olympiad_id", sa.Integer(), nullable=False),
        _text("site_url"),
        _text("summary"),
        _text("grades"),
        _list("formats"),
        _list("stages"),
        _text("source_url"),
        sa.Column("checked", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["olympiad_id"],
            ["olympiads.id"],
            name=op.f("fk_olympiad_info_olympiad_id_olympiads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_olympiad_info")),
        sa.UniqueConstraint("olympiad_id", name=op.f("uq_olympiad_info_olympiad_id")),
    )
    op.create_table(
        "olympiad_tracks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("olympiad_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(collation="C"), nullable=False),
        sa.Column("squash_key", sa.Text(collation="C"), nullable=False),
        _list("topics"),
        _text("source_url"),
        sa.Column("checked", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["olympiad_id"],
            ["olympiads.id"],
            name=op.f("fk_olympiad_tracks_olympiad_id_olympiads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["olympiad_profiles.id"],
            name=op.f("fk_olympiad_tracks_profile_id_olympiad_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_olympiad_tracks")),
        sa.UniqueConstraint(
            "olympiad_id", "squash_key", name=op.f("uq_olympiad_tracks_olympiad_id_squash_key")
        ),
    )
    op.create_index(op.f("ix_olympiad_tracks_profile_id"), "olympiad_tracks", ["profile_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_olympiad_tracks_profile_id"), table_name="olympiad_tracks")
    op.drop_table("olympiad_tracks")
    op.drop_table("olympiad_info")
