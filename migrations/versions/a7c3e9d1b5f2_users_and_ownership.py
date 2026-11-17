"""users, and every person's data belongs to one of them

Until now the app was private to its administrators and nothing in it had an owner. Now several people can have
accounts, each with completely private finances: users, and an owner on every table that holds budget data.

Everything that exists now is parked on a placeholder user (legacy-owner@finances.invalid); the first administrator to
sign in takes the placeholder over by giving it their email (app/crud.py adopt_or_create_admin), so it all becomes
theirs without moving a row.

What used to be unique across the whole table is unique per owner now: a person's or category's name, a provider
reference on a recurring item, an import's source + external id, a trip's or list's settlement, a month's opening
balance, and each setting's key (app_settings gets an id and an owner: its key alone can no longer be its primary key).

Revision ID: a7c3e9d1b5f2
Revises: f6b1d84a20c7
Create Date: 2026-11-17 14:00:00.000000

"""
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9d1b5f2"
down_revision: Union[str, Sequence[str], None] = "f6b1d84a20c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_OWNER_EMAIL = "legacy-owner@finances.invalid"
# Parents before children (the order they are filled in); app_settings is rebuilt separately below.
OWNED = (
    "people", "categories", "recurring_items", "funds", "transactions", "trip_settlements", "linked_lists",
    "payment_deferrals", "daily_spend", "month_opening_balances", "scenarios", "scenario_adjustments",
)

# SQLite reports the old unnamed UNIQUE constraints only if told how they would have been named, which lets batch mode drop them.
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

# (table, constraint it has now, columns that make the new per-owner one) - the new one is named uq_<table>_owner_id_<...>.
UNIQUES = (
    ("people", "uq_people_name", ["name"], "uq_people_owner_id_name"),
    ("categories", "uq_categories_name", ["name"], "uq_categories_owner_id_name"),
    ("recurring_items", "uq_recurring_reference_id", ["reference_id"], "uq_recurring_owner_id_reference_id"),
    ("transactions", "uq_transaction_source_external", ["source", "external_id"], "uq_transaction_owner_source_external"),
    ("trip_settlements", "uq_trip_settlements_trip_id", ["trip_id"], "uq_trip_settlements_owner_id_trip_id"),
    ("linked_lists", "uq_linked_lists_list_id", ["list_id"], "uq_linked_lists_owner_id_list_id"),
    ("month_opening_balances", "uq_month_opening_balances_month", ["month"], "uq_month_opening_balances_owner_id_month"),
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO users (email, status, created_at) VALUES (:email, 'active', :now)"),
        {"email": LEGACY_OWNER_EMAIL, "now": datetime.utcnow()},
    )
    legacy_id = conn.execute(sa.text("SELECT id FROM users WHERE email = :e"), {"e": LEGACY_OWNER_EMAIL}).scalar()

    # owner_id starts nullable so the existing rows can be filled in.
    for table in OWNED:
        with op.batch_alter_table(table, naming_convention=NAMING) as batch_op:
            batch_op.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(f"fk_{table}_owner_id_users", "users", ["owner_id"], ["id"])
        conn.execute(sa.text(f"UPDATE {table} SET owner_id = :owner"), {"owner": legacy_id})

    for table in OWNED:
        with op.batch_alter_table(table, naming_convention=NAMING) as batch_op:
            batch_op.alter_column("owner_id", existing_type=sa.Integer(), nullable=False)
            batch_op.create_index(f"ix_{table}_owner_id", ["owner_id"])

    for table, old, columns, new in UNIQUES:
        with op.batch_alter_table(table, naming_convention=NAMING) as batch_op:
            batch_op.drop_constraint(old, type_="unique")
            batch_op.create_unique_constraint(new, ["owner_id", *columns])

    # app_settings: the key alone was the primary key. Rebuilt with an id, an owner, and a key unique per owner.
    op.create_table(
        "app_settings_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_app_settings_owner_id_users"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "key", name="uq_app_settings_owner_id_key"),
    )
    conn.execute(
        sa.text('INSERT INTO app_settings_new (owner_id, "key", value) SELECT :owner, "key", value FROM app_settings'),
        {"owner": legacy_id},
    )
    op.drop_table("app_settings")
    op.rename_table("app_settings_new", "app_settings")
    op.create_index("ix_app_settings_owner_id", "app_settings", ["owner_id"])


def downgrade() -> None:
    """Downgrade schema. Fails if two people have a category or person name, a provider reference or the like in
    common (the old schema had one table-wide namespace), and everyone's data ends up in one place."""
    conn = op.get_bind()
    op.drop_index("ix_app_settings_owner_id", table_name="app_settings")
    op.create_table(
        "app_settings_old",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    # One value per key survives (the lowest-numbered owner's), which is everyone's own when there is only one owner.
    conn.execute(
        sa.text(
            'INSERT INTO app_settings_old ("key", value) '
            'SELECT "key", value FROM app_settings WHERE id IN (SELECT MIN(id) FROM app_settings GROUP BY "key")'
        )
    )
    op.drop_table("app_settings")
    op.rename_table("app_settings_old", "app_settings")

    for table, old, columns, new in reversed(UNIQUES):
        with op.batch_alter_table(table, naming_convention=NAMING) as batch_op:
            batch_op.drop_constraint(new, type_="unique")
            batch_op.create_unique_constraint(old, columns)
    for table in reversed(OWNED):
        with op.batch_alter_table(table, naming_convention=NAMING) as batch_op:
            batch_op.drop_index(f"ix_{table}_owner_id")
            batch_op.drop_constraint(f"fk_{table}_owner_id_users", type_="foreignkey")
            batch_op.drop_column("owner_id")
    op.drop_table("users")
