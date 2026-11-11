"""create bookings

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # GiST has no equality operator class for uuid without btree_gist.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        # create_table also creates the enum type.
        sa.Column(
            "status",
            sa.Enum("CONFIRMED", "CANCELLED", name="booking_status"),
            server_default="CONFIRMED",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_bookings_ends_at_after_starts_at")),
        sa.CheckConstraint(
            "party_size BETWEEN 1 AND 8", name=op.f("ck_bookings_party_size_between_1_and_8")
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["dining_tables.id"],
            name=op.f("fk_bookings_table_id_dining_tables"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_bookings_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        postgresql.ExcludeConstraint(
            (sa.column("table_id"), "="),
            (sa.func.tstzrange(sa.column("starts_at"), sa.column("ends_at")), "&&"),
            name="ex_bookings_table_id_period",
            using="gist",
            where=sa.text("status = 'CONFIRMED'"),
        ),
    )
    op.create_index(op.f("ix_bookings_user_id"), "bookings", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bookings_user_id"), table_name="bookings")
    op.drop_table("bookings")
    # drop_table leaves the type behind, and the next upgrade would fail to create it again.
    sa.Enum(name="booking_status").drop(op.get_bind())
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
