"""add staff and request decisions

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXCLUSION_CONSTRAINT = "ex_bookings_table_id_period"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_staff", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # The new value cannot be used before this transaction commits, so nothing below touches it.
    op.execute("ALTER TYPE booking_status ADD VALUE 'REJECTED'")
    op.add_column("bookings", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("decided_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_bookings_decided_by_id_users"),
        "bookings",
        "users",
        ["decided_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_bookings_decided_by_id"), "bookings", ["decided_by_id"], unique=False)


def downgrade() -> None:
    op.execute("UPDATE bookings SET status = 'CANCELLED' WHERE status::text = 'REJECTED'")
    op.drop_index(op.f("ix_bookings_decided_by_id"), table_name="bookings")
    op.drop_constraint(op.f("fk_bookings_decided_by_id_users"), "bookings", type_="foreignkey")
    op.drop_column("bookings", "decided_by_id")
    op.drop_column("bookings", "decided_at")
    # The default and the partial constraint both depend on the type, so they are rebuilt with it.
    op.execute("ALTER TABLE bookings ALTER COLUMN status DROP DEFAULT")
    op.drop_constraint(EXCLUSION_CONSTRAINT, "bookings")
    # PostgreSQL has no DROP VALUE, so the type is rebuilt without the label.
    op.execute("ALTER TYPE booking_status RENAME TO booking_status_old")
    op.execute("CREATE TYPE booking_status AS ENUM ('CONFIRMED', 'CANCELLED', 'PENDING')")
    op.execute(
        "ALTER TABLE bookings ALTER COLUMN status TYPE booking_status "
        "USING status::text::booking_status"
    )
    op.execute("DROP TYPE booking_status_old")
    op.execute("ALTER TABLE bookings ALTER COLUMN status SET DEFAULT 'CONFIRMED'")
    op.execute(
        f"ALTER TABLE bookings ADD CONSTRAINT {EXCLUSION_CONSTRAINT} "
        "EXCLUDE USING gist (table_id WITH =, tstzrange(starts_at, ends_at) WITH &&) "
        "WHERE (status = 'CONFIRMED')"
    )
    op.drop_column("users", "is_staff")
