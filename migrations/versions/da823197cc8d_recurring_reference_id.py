"""recurring reference_id

Revision ID: da823197cc8d
Revises: d17f8183844f
Create Date: 2026-08-29 09:41:40.660379

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da823197cc8d'
down_revision: Union[str, Sequence[str], None] = 'd17f8183844f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Optional provider reference for a "pay in N months" plan, unique so an
    # accidental duplicate entry is caught.
    with op.batch_alter_table('recurring_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reference_id', sa.String(), nullable=True))
        batch_op.create_unique_constraint('uq_recurring_reference_id', ['reference_id'])


def downgrade() -> None:
    with op.batch_alter_table('recurring_items', schema=None) as batch_op:
        batch_op.drop_constraint('uq_recurring_reference_id', type_='unique')
        batch_op.drop_column('reference_id')
