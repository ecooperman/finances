"""rename seeded Spouse person to Rach

Revision ID: 31dd6252df2f
Revises: 4b660f86dd67
Create Date: 2026-08-28 12:24:32.504444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31dd6252df2f'
down_revision: Union[str, Sequence[str], None] = '4b660f86dd67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The baseline seeded a placeholder "Spouse" person; Evan's is "Rach".
    # Only touches the row if it's still the untouched placeholder (no-op on
    # a DB where it was already renamed by hand, or on a fresh DB where the
    # updated baseline now seeds "Rach" directly).
    op.execute("UPDATE people SET name = 'Rach' WHERE name = 'Spouse'")


def downgrade() -> None:
    op.execute("UPDATE people SET name = 'Spouse' WHERE name = 'Rach'")
