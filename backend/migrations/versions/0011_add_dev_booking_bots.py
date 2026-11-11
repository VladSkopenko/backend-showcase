"""add dev booking bots

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.config.settings import get_settings

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATED = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Lf2JoTtceyf2Fd6S/nVkYg$"
    "DtRYerfEvFEpwj+u7XZvNnKmV8N8DGK0iDm+br4R0OM"
)

BOT_NUMBERS = range(1, 5)

EMAILS = [f"booking-bot-{number}@example.com" for number in BOT_NUMBERS]

users = sa.table(
    "users",
    sa.column("first_name", sa.String),
    sa.column("last_name", sa.String),
    sa.column("email", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("email_verified_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    op.bulk_insert(
        users,
        [
            {
                "first_name": "Booking",
                "last_name": f"Bot {number}",
                "email": email,
                "password_hash": PASSWORD_HASH,
                "email_verified_at": CREATED,
                "created_at": CREATED,
                "updated_at": CREATED,
            }
            for number, email in zip(BOT_NUMBERS, EMAILS, strict=True)
        ],
    )


def downgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    op.execute(users.delete().where(users.c.email.in_(EMAILS)))
