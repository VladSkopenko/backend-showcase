"""add postgres exporter role

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-20 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

from app.config.settings import get_settings

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "postgres_exporter"

VERIFIER = (
    "SCRAM-SHA-256$4096:Ki+c/1+ana2nnsotNxsokQ==$"
    "YsK96/0YPzfkfM9kXtRFvUt3rqswDKq9gxxmITDEj1s=:zUHZZaeQ9HUyxSzWJcvbYTCvfQiPnx0DDLLwrX622ZA="
)


def upgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    op.get_bind().exec_driver_sql(
        f"CREATE ROLE {ROLE} LOGIN PASSWORD '{VERIFIER}' CONNECTION LIMIT 5"
    )
    op.execute(f"ALTER ROLE {ROLE} SET statement_timeout = '5s'")
    op.execute(f"ALTER ROLE {ROLE} SET default_transaction_read_only = on")


def downgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    op.execute(f"DROP ROLE {ROLE}")
