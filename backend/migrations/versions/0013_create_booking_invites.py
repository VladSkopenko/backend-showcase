"""create booking invites

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_invites",
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_booking_invites_booking_id_bookings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("booking_id", name=op.f("pk_booking_invites")),
        sa.UniqueConstraint("code", name=op.f("uq_booking_invites_code")),
    )


def downgrade() -> None:
    op.drop_table("booking_invites")
