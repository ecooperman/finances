"""Payments that couldn't be made this month and roll into the next.

See `models.PaymentDeferral` for the row semantics. This module owns the
mutations (defer / carry again / undo) and the month arithmetic; the monthly
rollup and the paycheck lookahead only read the rows.
"""

from sqlalchemy.orm import Session

from .. import models
from .monthly import _recurring_amount, _weekly_days
from .schedule import active_in_month, cadence_hits, shift_month


class DeferralError(Exception):
    """A request that can't be honoured; `status` is the HTTP code to use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _month_amount(item: models.RecurringItem, month: str) -> int:
    """What the item would have cost in `month` (cash flow): every real pay
    day for a dated weekly/biweekly item, else its normal monthly figure."""
    y, m = (int(p) for p in month.split("-"))
    days = _weekly_days(item, y, m)
    if days is not None:
        return item.amount_cents * len(days)
    return _recurring_amount(item.frequency, item.amount_cents, False)


def defer_payment(db: Session, item_id: int, month: str) -> models.PaymentDeferral:
    item = db.get(models.RecurringItem, item_id)
    if item is None:
        raise DeferralError("Recurring item not found", 404)
    if item.direction != "out":
        raise DeferralError("Only money-out items can be carried over")
    mon = int(month[5:7])
    if not active_in_month(item, month) or not cadence_hits(item.frequency, item.anchor_month, mon):
        raise DeferralError("That item has no payment due in that month")
    existing = (
        db.query(models.PaymentDeferral)
        .filter_by(recurring_item_id=item_id, month=month, origin_id=None)
        .first()
    )
    if existing is not None:
        raise DeferralError("That payment is already carried over", 409)
    row = models.PaymentDeferral(
        recurring_item_id=item_id,
        month=month,
        original_month=month,
        amount_cents=_month_amount(item, month),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def defer_transaction(db: Session, txn_id: int) -> models.PaymentDeferral:
    """Carry a one-off money-out transaction (in the month it's dated) forward."""
    txn = db.get(models.Transaction, txn_id)
    if txn is None:
        raise DeferralError("Transaction not found", 404)
    if txn.direction != "out":
        raise DeferralError("Only money-out items can be carried over")
    if db.query(models.PaymentDeferral).filter_by(transaction_id=txn_id, origin_id=None).first():
        raise DeferralError("That payment is already carried over", 409)
    month = txn.date.strftime("%Y-%m")
    row = models.PaymentDeferral(
        transaction_id=txn_id, month=month, original_month=month, amount_cents=txn.amount_cents
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def carry_again(db: Session, origin_id: int) -> models.PaymentDeferral:
    origin = db.get(models.PaymentDeferral, origin_id)
    if origin is None:
        raise DeferralError("Carried-over payment not found", 404)
    if db.query(models.PaymentDeferral).filter_by(origin_id=origin_id).first() is not None:
        raise DeferralError("That payment is already carried over again", 409)
    row = models.PaymentDeferral(
        recurring_item_id=origin.recurring_item_id,
        transaction_id=origin.transaction_id,
        month=shift_month(origin.month, 1),
        original_month=origin.original_month,
        amount_cents=origin.amount_cents,
        origin_id=origin.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def undo_deferral(db: Session, deferral_id: int) -> bool:
    """Delete a deferral and any later carries that continued it."""
    row = db.get(models.PaymentDeferral, deferral_id)
    if row is None:
        return False
    frontier = [row.id]
    doomed = []
    while frontier:
        doomed.extend(frontier)
        frontier = [
            d.id for d in db.query(models.PaymentDeferral)
            .filter(models.PaymentDeferral.origin_id.in_(frontier)).all()
        ]
    db.query(models.PaymentDeferral).filter(models.PaymentDeferral.id.in_(doomed)).delete(
        synchronize_session=False
    )
    db.commit()
    return True


def clear_for(db: Session, *, recurring_item_id=None, transaction_id=None) -> None:
    """Drop every deferral (whole chains) tied to a recurring item or
    transaction that is being deleted/converted. SQLite isn't enforcing the
    FK cascades, so callers do this explicitly. Doesn't commit."""
    q = db.query(models.PaymentDeferral)
    if recurring_item_id is not None:
        q = q.filter_by(recurring_item_id=recurring_item_id)
    else:
        q = q.filter_by(transaction_id=transaction_id)
    q.delete(synchronize_session=False)
