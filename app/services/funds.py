"""Sinking-fund math: the monthly set-aside and the running balance.

A fund contributes `annual_amount_cents / 12` to the *provisioning* figure
every month (see services/monthly.py - it never touches cash flow). Its
balance carries over across years:

    balance = (months accrued since start_month) * monthly_contribution
            - (every fund-tagged `out` transaction to date)

so a year where you underspend leaves a positive balance that rolls
forward, and an overspend rolls forward negative.
"""

from calendar import monthrange
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models


def current_month() -> str:
    t = date.today()
    return f"{t.year:04d}-{t.month:02d}"


def _parts(month: str):
    y, m = (int(p) for p in month.split("-"))
    return y, m


def _month_end(month: str) -> date:
    y, m = _parts(month)
    return date(y, m, monthrange(y, m)[1])


def months_elapsed(start_month: str, as_of_month: str) -> int:
    """Inclusive count of months from start_month through as_of_month;
    0 if as_of_month is earlier than start_month."""
    sy, sm = _parts(start_month)
    ay, am = _parts(as_of_month)
    return max((ay - sy) * 12 + (am - sm) + 1, 0)


def monthly_contribution_cents(fund: models.SinkingFund) -> int:
    return round(fund.annual_amount_cents / 12)


def fund_status(db: Session, fund: models.SinkingFund, as_of_month: Optional[str] = None) -> dict:
    as_of_month = as_of_month or current_month()
    monthly = monthly_contribution_cents(fund)
    accrued = months_elapsed(fund.start_month, as_of_month) * monthly

    end = _month_end(as_of_month)
    spent = (
        db.query(func.sum(models.Transaction.amount_cents))
        .filter(
            models.Transaction.fund_id == fund.id,
            models.Transaction.direction == "out",
            models.Transaction.date <= end,
        )
        .scalar()
        or 0
    )
    year_start = date(_parts(as_of_month)[0], 1, 1)
    spent_ytd = (
        db.query(func.sum(models.Transaction.amount_cents))
        .filter(
            models.Transaction.fund_id == fund.id,
            models.Transaction.direction == "out",
            models.Transaction.date >= year_start,
            models.Transaction.date <= end,
        )
        .scalar()
        or 0
    )
    return {
        "monthly_contribution_cents": monthly,
        "accrued_cents": accrued,
        "spent_cents": spent,
        "balance_cents": accrued - spent,
        "spent_ytd_cents": spent_ytd,
    }


def funds_summary(db: Session, as_of_month: Optional[str] = None) -> dict:
    """Fleet-wide roll-up for the Overview status line and the Budget footer."""
    as_of_month = as_of_month or current_month()
    funds = db.query(models.SinkingFund).filter(models.SinkingFund.active.is_(True)).all()
    monthly_total = banked_total = 0
    for f in funds:
        st = fund_status(db, f, as_of_month)
        monthly_total += st["monthly_contribution_cents"]
        banked_total += st["balance_cents"]
    return {
        "active_count": len(funds),
        "monthly_total_cents": monthly_total,
        "banked_total_cents": banked_total,
    }
