"""deferrals can target transactions

Revision ID: 5eac41ea42d9
Revises: e19cbb24387b
Create Date: 2026-10-02 11:24:48.747900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5eac41ea42d9'
down_revision: Union[str, Sequence[str], None] = 'e19cbb24387b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('payment_deferrals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transaction_id', sa.Integer(), nullable=True))
        batch_op.alter_column('recurring_item_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.create_foreign_key(
            'fk_payment_deferrals_transaction_id_transactions',
            'transactions', ['transaction_id'], ['id'], ondelete='CASCADE')
        batch_op.create_check_constraint(
            'ck_payment_deferrals_one_target',
            '(recurring_item_id IS NOT NULL) + (transaction_id IS NOT NULL) = 1')


def downgrade() -> None:
    """Downgrade schema."""
    # transaction deferrals have no recurring item to point at in the old shape
    op.execute('DELETE FROM payment_deferrals WHERE transaction_id IS NOT NULL')
    with op.batch_alter_table('payment_deferrals', schema=None) as batch_op:
        batch_op.drop_constraint('ck_payment_deferrals_one_target', type_='check')
        batch_op.drop_constraint('fk_payment_deferrals_transaction_id_transactions', type_='foreignkey')
        batch_op.alter_column('recurring_item_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('transaction_id')
