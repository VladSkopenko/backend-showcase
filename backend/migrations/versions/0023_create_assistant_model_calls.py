"""create assistant model calls and index user messages by time

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_model_calls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_model_calls")),
    )
    op.create_index(
        op.f("ix_assistant_model_calls_created_at"),
        "assistant_model_calls",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_messages_user_created_at",
        "assistant_messages",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("role = 'USER'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_messages_user_created_at",
        table_name="assistant_messages",
        postgresql_where=sa.text("role = 'USER'"),
    )
    op.drop_index(op.f("ix_assistant_model_calls_created_at"), table_name="assistant_model_calls")
    op.drop_table("assistant_model_calls")
