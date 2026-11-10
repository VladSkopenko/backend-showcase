"""create dining tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = {
    "48-rustaveli-avenue": [(2, 3), (4, 4), (6, 2), (8, 1)],
    "14-baratashvili-street": [(2, 4), (4, 7), (6, 3), (8, 2)],
    "9-abashidze-street": [(2, 5), (4, 9), (6, 4), (8, 2)],
}

locations = sa.table("locations", sa.column("id", sa.Uuid), sa.column("slug", sa.String))


def upgrade() -> None:
    dining_tables = op.create_table(
        "dining_tables",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "capacity BETWEEN 2 AND 8", name=op.f("ck_dining_tables_capacity_between_2_and_8")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_dining_tables_location_id_locations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dining_tables")),
        sa.UniqueConstraint("location_id", "label", name="uq_dining_tables_location_id_label"),
    )
    seed = sa.values(
        sa.column("slug", sa.String),
        sa.column("label", sa.String),
        sa.column("capacity", sa.Integer),
        name="seed",
    ).data(
        [
            (slug, f"Table {number}", capacity)
            for slug, groups in TABLES.items()
            for number, capacity in enumerate(
                (capacity for capacity, count in groups for _ in range(count)), start=1
            )
        ]
    )
    op.execute(
        dining_tables.insert().from_select(
            ["location_id", "label", "capacity"],
            sa.select(locations.c.id, seed.c.label, seed.c.capacity).join_from(
                seed, locations, locations.c.slug == seed.c.slug
            ),
        )
    )


def downgrade() -> None:
    op.drop_table("dining_tables")
