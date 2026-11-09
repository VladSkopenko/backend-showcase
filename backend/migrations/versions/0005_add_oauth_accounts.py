"""add oauth accounts

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_oauth_accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # create_table also creates the enum type.
        sa.Column("provider", sa.Enum("GOOGLE", name="oauth_provider"), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_oauth_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_oauth_accounts")),
        sa.UniqueConstraint(
            "provider", "subject", name=op.f("uq_user_oauth_accounts_provider_subject")
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name=op.f("uq_user_oauth_accounts_user_id_provider")
        ),
    )
    op.create_index(
        op.f("ix_user_oauth_accounts_user_id"), "user_oauth_accounts", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_oauth_accounts_user_id"), table_name="user_oauth_accounts")
    op.drop_table("user_oauth_accounts")
    # drop_table leaves the type behind, and the next upgrade would fail to create it again.
    sa.Enum(name="oauth_provider").drop(op.get_bind())
