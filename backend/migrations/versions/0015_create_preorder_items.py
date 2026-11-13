"""create preorder items

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preorder_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("dish_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "state", sa.Enum("DRAFT", "SUBMITTED", name="preorder_item_state"), nullable=False
        ),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_preorder_items_quantity_positive")),
        sa.CheckConstraint(
            "(state = 'DRAFT') = (submission_id IS NULL) "
            "AND (submission_id IS NULL) = (submitted_at IS NULL)",
            name=op.f("ck_preorder_items_submission_matches_state"),
        ),
        sa.ForeignKeyConstraint(
            ["dish_id"],
            ["dishes.id"],
            name=op.f("fk_preorder_items_dish_id_dishes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["booking_participants.id"],
            name=op.f("fk_preorder_items_participant_id_booking_participants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preorder_items")),
    )
    op.create_index(
        "ix_preorder_items_participant_id_dish_id_draft",
        "preorder_items",
        ["participant_id", "dish_id"],
        unique=True,
        postgresql_where=sa.text("state = 'DRAFT'"),
    )
    op.create_index(
        op.f("ix_preorder_items_participant_id"),
        "preorder_items",
        ["participant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("preorder_items")
    sa.Enum(name="preorder_item_state").drop(op.get_bind())
