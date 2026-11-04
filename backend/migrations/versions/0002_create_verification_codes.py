"""create verification codes

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "verification_codes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # create_table also creates the enum type.
        sa.Column(
            "purpose",
            sa.Enum("EMAIL_VERIFICATION", name="verification_purpose"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_verification_codes_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_codes")),
    )


def downgrade() -> None:
    op.drop_table("verification_codes")
    # drop_table leaves the type behind, and the next upgrade would fail to create it again.
    sa.Enum(name="verification_purpose").drop(op.get_bind())
    op.drop_column("users", "email_verified_at")
