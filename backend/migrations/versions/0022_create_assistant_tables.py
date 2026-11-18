"""create assistant tables

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_assistant_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_sessions")),
    )
    op.create_index(
        "ix_assistant_sessions_user_id_updated_at",
        "assistant_sessions",
        ["user_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role", sa.Enum("USER", "ASSISTANT", name="assistant_message_role"), nullable=False
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["assistant_sessions.id"],
            name=op.f("fk_assistant_messages_session_id_assistant_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_messages")),
    )
    op.create_index(
        "ix_assistant_messages_session_id_created_at_id",
        "assistant_messages",
        ["session_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("assistant_messages")
    sa.Enum(name="assistant_message_role").drop(op.get_bind())
    op.drop_table("assistant_sessions")
