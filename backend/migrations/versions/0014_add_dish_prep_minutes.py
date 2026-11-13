"""add dish prep minutes

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dishes", sa.Column("prep_minutes", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE dishes SET prep_minutes = CASE category "
        "WHEN 'APPETIZER' THEN 10 WHEN 'MAIN_COURSE' THEN 20 WHEN 'DESSERT' THEN 10 END"
    )
    op.alter_column("dishes", "prep_minutes", nullable=False)
    op.create_check_constraint(
        op.f("ck_dishes_prep_minutes_positive"), "dishes", "prep_minutes > 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_dishes_prep_minutes_positive"), "dishes", type_="check")
    op.drop_column("dishes", "prep_minutes")
