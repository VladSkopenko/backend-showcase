"""create notifications

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "BOOKING_REQUEST_APPROVED", "BOOKING_REQUEST_REJECTED", name="notification_kind"
            ),
            nullable=False,
        ),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_notifications_booking_id_bookings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_booking_id"), "notifications", ["booking_id"], unique=False
    )
    op.create_index(
        "ix_notifications_user_id_created_at_id",
        "notifications",
        ["user_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("notifications")
    sa.Enum(name="notification_kind").drop(op.get_bind())
