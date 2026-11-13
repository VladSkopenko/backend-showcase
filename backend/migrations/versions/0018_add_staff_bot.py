"""add staff bot

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-13 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.config.settings import get_settings

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATED = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

# The bot password hash of 0011, so every bot signs in with the same password.
PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Lf2JoTtceyf2Fd6S/nVkYg$"
    "DtRYerfEvFEpwj+u7XZvNnKmV8N8DGK0iDm+br4R0OM"
)

EMAIL = "waiter-bot@example.com"

ENVIRONMENTS = ("dev", "local")

users = sa.table(
    "users",
    sa.column("first_name", sa.String),
    sa.column("last_name", sa.String),
    sa.column("email", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("email_verified_at", sa.DateTime(timezone=True)),
    sa.column("is_staff", sa.Boolean),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    if get_settings().app.environment not in ENVIRONMENTS:
        return
    op.bulk_insert(
        users,
        [
            {
                "first_name": "Waiter",
                "last_name": "Bot",
                "email": EMAIL,
                "password_hash": PASSWORD_HASH,
                "email_verified_at": CREATED,
                "is_staff": True,
                "created_at": CREATED,
                "updated_at": CREATED,
            }
        ],
    )


def downgrade() -> None:
    if get_settings().app.environment not in ENVIRONMENTS:
        return
    op.execute(users.delete().where(users.c.email == EMAIL))
