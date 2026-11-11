"""create booking participants

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guests")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_guests_token_hash")),
    )
    op.create_table(
        "booking_participants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("guest_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.Enum("OWNER", "GUEST", name="participant_role"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_id) = 1",
            name=op.f("ck_booking_participants_one_of_user_id_guest_id"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_booking_participants_booking_id_bookings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guest_id"],
            ["guests.id"],
            name=op.f("fk_booking_participants_guest_id_guests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_booking_participants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_participants")),
        sa.UniqueConstraint(
            "booking_id", "guest_id", name="uq_booking_participants_booking_id_guest_id"
        ),
        sa.UniqueConstraint(
            "booking_id", "user_id", name="uq_booking_participants_booking_id_user_id"
        ),
    )
    op.create_index(
        "ix_booking_participants_booking_id_owner",
        "booking_participants",
        ["booking_id"],
        unique=True,
        postgresql_where=sa.text("role = 'OWNER'"),
    )
    op.create_index(
        op.f("ix_booking_participants_guest_id"),
        "booking_participants",
        ["guest_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_booking_participants_user_id"),
        "booking_participants",
        ["user_id"],
        unique=False,
    )
    op.execute(
        "INSERT INTO booking_participants (booking_id, user_id, role, created_at) "
        "SELECT id, user_id, 'OWNER', created_at FROM bookings"
    )


def downgrade() -> None:
    op.drop_table("booking_participants")
    op.drop_table("guests")
    sa.Enum(name="participant_role").drop(op.get_bind())
