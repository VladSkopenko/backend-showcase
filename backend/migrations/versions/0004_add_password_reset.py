"""add password reset

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FOREIGN_KEY = "fk_verification_codes_user_id_users"
INDEX = "ix_verification_codes_user_id_purpose_created_at"


def upgrade() -> None:
    # The new value cannot be used before this transaction commits, so nothing below touches it.
    op.execute("ALTER TYPE verification_purpose ADD VALUE 'PASSWORD_RESET'")
    op.drop_constraint(op.f(FOREIGN_KEY), "verification_codes", type_="foreignkey")
    op.create_foreign_key(
        op.f(FOREIGN_KEY),
        "verification_codes",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f(INDEX), "verification_codes", ["user_id", "purpose", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f(INDEX), table_name="verification_codes")
    op.drop_constraint(op.f(FOREIGN_KEY), "verification_codes", type_="foreignkey")
    op.create_foreign_key(op.f(FOREIGN_KEY), "verification_codes", "users", ["user_id"], ["id"])
    op.execute("DELETE FROM verification_codes WHERE purpose::text = 'PASSWORD_RESET'")
    # PostgreSQL has no DROP VALUE, so the type is rebuilt without the label.
    op.execute("ALTER TYPE verification_purpose RENAME TO verification_purpose_old")
    op.execute("CREATE TYPE verification_purpose AS ENUM ('EMAIL_VERIFICATION')")
    op.execute(
        "ALTER TABLE verification_codes ALTER COLUMN purpose TYPE verification_purpose "
        "USING purpose::text::verification_purpose"
    )
    op.execute("DROP TYPE verification_purpose_old")
