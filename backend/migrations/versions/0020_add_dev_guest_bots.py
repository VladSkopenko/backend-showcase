"""add dev guest bots

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-13 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from app.config.settings import get_settings

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATED = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

# The bot password hash of 0011, so every bot signs in with the same password.
PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Lf2JoTtceyf2Fd6S/nVkYg$"
    "DtRYerfEvFEpwj+u7XZvNnKmV8N8DGK0iDm+br4R0OM"
)

NAMES = [
    ("Nino", "Beridze"),
    ("Giorgi", "Kapanadze"),
    ("Tamar", "Gelashvili"),
    ("Davit", "Lomidze"),
    ("Ana", "Tsiklauri"),
    ("Levan", "Mchedlishvili"),
    ("Mariam", "Japaridze"),
    ("Irakli", "Chikovani"),
    ("Salome", "Gogoladze"),
    ("Luka", "Dolidze"),
    ("Ketevan", "Nozadze"),
    ("Nikoloz", "Kiknadze"),
    ("Eka", "Sulaberidze"),
    ("Sandro", "Tabatadze"),
    ("Natia", "Khutsishvili"),
    ("Zurab", "Kiladze"),
    ("Tekla", "Jgerenaia"),
    ("Lasha", "Gvenetadze"),
    ("Maia", "Tsertsvadze"),
    ("Otar", "Gabunia"),
    ("Elene", "Kharaishvili"),
    ("Beka", "Natsvlishvili"),
    ("Emma", "Schneider"),
    ("Lukas", "Weber"),
    ("Sofia", "Rossi"),
    ("Marco", "Bianchi"),
    ("Olivia", "Bennett"),
    ("Daniel", "Novak"),
    ("Anna", "Kowalska"),
    ("Mehmet", "Yilmaz"),
    ("Elif", "Demir"),
    ("Yuki", "Tanaka"),
    ("Clara", "Dubois"),
    ("Hugo", "Laurent"),
    ("Lena", "Fischer"),
    ("Anahit", "Grigoryan"),
]

BOT_NUMBERS = range(5, 41)

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
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "password_hash": PASSWORD_HASH,
                "email_verified_at": CREATED,
                "created_at": CREATED,
                "updated_at": CREATED,
            }
            for (first_name, last_name), email in zip(NAMES, EMAILS, strict=True)
        ],
    )


def downgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    op.execute(users.delete().where(users.c.email.in_(EMAILS)))
