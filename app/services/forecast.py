"""The one rule for turning a lump-sum planned cost into a monthly set-aside - shared by trips
(a trip's cost, read live from trip-planning) and linked lists (a list's still-to-buy total, read
live from lists), so the two always behave identically.

A planned cost is a single amount plus the month it is due. Its cost is spread evenly over the months
from now through the due month (a sinking fund with a deadline); a cost that is already due, or due
this month, is "all due now". Nothing here stores anything.
"""
from typing import Optional

from .funds import months_elapsed


def place(row: dict, *, amount: int, month: Optional[str], excluded: bool, as_of_month: str, month_key: str) -> str:
    """Fill in the spread fields on `row` (under `month_key` for the due month) and say which bucket it
    belongs in: "excluded" (hidden from the forecast, kept visible), "no_date" (nothing to spread
    over yet), or "upcoming" (feeds the monthly provisioning math)."""
    if excluded:
        row.update({month_key: month, "months_remaining": None, "monthly_contribution_cents": 0})
        return "excluded"
    if month is None:
        row.update({month_key: None, "months_remaining": None, "monthly_contribution_cents": 0})
        return "no_date"
    if amount <= 0:
        # keep it visible (so an override can be set) but contribute nothing
        row.update(
            {month_key: month, "months_remaining": max(months_elapsed(as_of_month, month), 1), "monthly_contribution_cents": 0}
        )
        return "upcoming"
    # months from as_of through the due month, inclusive; an overdue or current-month cost is "all due now"
    months_remaining = months_elapsed(as_of_month, month)
    if months_remaining <= 1:
        per_month = amount
        months_remaining = max(months_remaining, 1)
    else:
        per_month = round(amount / months_remaining)
    row.update({month_key: month, "months_remaining": months_remaining, "monthly_contribution_cents": per_month})
    return "upcoming"
