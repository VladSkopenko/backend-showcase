"""create locations

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIRST = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

LOCATIONS = [
    {
        "slug": "48-rustaveli-avenue",
        "address": "48 Rustaveli Avenue",
        "description": (
            "Located on bustling Rustaveli Avenue, this branch offers a perfect mix of city "
            "energy and a cozy atmosphere. With its spacious outdoor terrace, this location is "
            "ideal for both casual lunches and intimate dinners."
        ),
    },
    {
        "slug": "14-baratashvili-street",
        "address": "14 Baratashvili Street",
        "description": (
            "Set on a quiet street at the edge of the old town, this branch pairs warm wooden "
            "interiors with a calm, green courtyard. Its long shared tables make it a favourite "
            "for family dinners and gatherings with friends."
        ),
    },
    {
        "slug": "9-abashidze-street",
        "address": "9 Abashidze Street",
        "description": (
            "In the leafy Vake district, this bright, plant-filled branch has a relaxed "
            "neighbourhood feel. Large windows and an open kitchen make it ideal for slow "
            "brunches and easy evenings."
        ),
    },
]


def upgrade() -> None:
    locations = op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("address", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("image_key", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint("slug", name=op.f("uq_locations_slug")),
    )
    op.bulk_insert(
        locations,
        [
            {
                **location,
                "image_key": f"locations/{location['slug']}.jpg",
                "created_at": FIRST + timedelta(minutes=position),
                "updated_at": FIRST + timedelta(minutes=position),
            }
            for position, location in enumerate(LOCATIONS)
        ],
    )


def downgrade() -> None:
    op.drop_table("locations")
