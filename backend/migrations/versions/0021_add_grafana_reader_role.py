"""add grafana reader role

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-17 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

from app.config.settings import get_settings

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "grafana_reader"

VERIFIER = (
    "SCRAM-SHA-256$4096:oAu9QEqC6ISBKHVq9jGsVw==$"
    "5aGOiFvnUluXQDOYgKE4iC6A9dwLLoNAMws3O0q/2m8=:sCqh6UQBpGZkQYKNV9QB5mwpn6NMK2JNo8hQQAxoE0U="
)

READABLE_COLUMNS = {
    "bookings": (
        "id",
        "user_id",
        "table_id",
        "party_size",
        "starts_at",
        "ends_at",
        "status",
        "decided_at",
        "decided_by_id",
        "created_at",
        "updated_at",
    ),
    "booking_participants": ("id", "booking_id", "user_id", "guest_id", "role", "created_at"),
    "dining_tables": ("id", "location_id", "label", "capacity"),
    "locations": (
        "id",
        "slug",
        "address",
        "description",
        "image_key",
        "created_at",
        "updated_at",
    ),
    "dishes": (
        "id",
        "slug",
        "name",
        "description",
        "category",
        "price_cents",
        "weight_grams",
        "calories",
        "protein",
        "fats",
        "carbs",
        "vitamins",
        "is_available",
        "popularity",
        "prep_minutes",
        "image_key",
        "created_at",
        "updated_at",
    ),
    "preorder_items": (
        "id",
        "participant_id",
        "dish_id",
        "quantity",
        "state",
        "submission_id",
        "submitted_at",
        "created_at",
        "updated_at",
    ),
    "users": ("id", "first_name", "last_name"),
}

LARGE_OBJECT_FUNCTIONS = "lo_creat(integer), lo_create(oid), lo_from_bytea(oid, bytea)"


def upgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    # Driver SQL: op.execute would read the ":" inside the verifier as bind parameters.
    op.get_bind().exec_driver_sql(
        f"CREATE ROLE {ROLE} LOGIN PASSWORD '{VERIFIER}' CONNECTION LIMIT 5"
    )
    op.execute(f"ALTER ROLE {ROLE} SET statement_timeout = '5s'")
    op.execute(f"ALTER ROLE {ROLE} SET default_transaction_read_only = on")
    op.execute(f"ALTER ROLE {ROLE} SET temp_file_limit = '64MB'")
    for table_name, columns in READABLE_COLUMNS.items():
        op.execute(f"GRANT SELECT ({', '.join(columns)}) ON {table_name} TO {ROLE}")
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        "'REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$"
    )
    op.execute(f"REVOKE EXECUTE ON FUNCTION {LARGE_OBJECT_FUNCTIONS} FROM PUBLIC")


def downgrade() -> None:
    if get_settings().app.environment != "dev":
        return
    op.execute(f"GRANT EXECUTE ON FUNCTION {LARGE_OBJECT_FUNCTIONS} TO PUBLIC")
    op.execute(
        "DO $$ BEGIN EXECUTE format("
        "'GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database()); END $$"
    )
    op.execute(f"DROP OWNED BY {ROLE}")
    op.execute(f"DROP ROLE {ROLE}")
