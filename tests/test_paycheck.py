"""The "how much is left to pay until the next paycheck" lookahead."""

from datetime import date

from app import models
from app.services.paycheck import until_next_paycheck
from app.services.schedule import occurrence_days


def _item(db, **kw):
    kw.setdefault("direction", "out")
    kw.setdefault("frequency", "monthly")
    kw.setdefault("active", True)
    item = models.RecurringItem(**kw)
    db.add(item)
    db.commit()
    return item


def _person(db, name):
    p = models.Person(name=name, color="#111")
    db.add(p)
    db.commit()
    return p


# --- occurrence_days ---------------------------------------------------


def test_biweekly_phase_comes_from_the_anchor():
    # Fridays in Oct 2026: 2, 9, 16, 23, 30. Anchor Oct 2 -> 2, 16, 30.
    assert occurrence_days("biweekly", None, 5, date(2026, 10, 2), 2026, 10) == [2, 16, 30]
    # Anchor a week earlier (Sep 25) -> the other phase: 9, 23.
    assert occurrence_days("biweekly", None, 5, date(2026, 9, 25), 2026, 10) == [9, 23]
    # Phase carries across a year boundary (anchor is in the past).
    assert occurrence_days("biweekly", None, 5, date(2026, 10, 2), 2027, 1) == [8, 22]  # Oct 2 + 14d steps: ... Dec 25, Jan 8, Jan 22


def test_day_31_clamps_to_month_end_and_undated_is_none():
    assert occurrence_days("monthly", 31, None, None, 2026, 9) == [30]
    assert occurrence_days("monthly", None, None, None, 2026, 9) is None
    assert occurrence_days("weekly", None, None, None, 2026, 9) is None


# --- the lookahead -----------------------------------------------------


def test_totals_what_is_due_before_the_next_paycheck(db):
    # Paycheck Fri Oct 16 (every 14 days from Oct 2); today is Oct 3.
    _item(db, name="Paycheck", amount_cents=600_000, direction="in",
          frequency="biweekly", day_of_week=5, week_anchor=date(2026, 10, 2))
    _item(db, name="Loan A", amount_cents=10_000, day_of_month=5)   # before
    _item(db, name="Loan B", amount_cents=20_000, day_of_month=15)  # before
    _item(db, name="Loan C", amount_cents=30_000, day_of_month=16)  # payday itself
    _item(db, name="Loan D", amount_cents=40_000, day_of_month=20)  # after
    _item(db, name="Past", amount_cents=99_000, day_of_month=1)     # already gone

    res = until_next_paycheck(db, date(2026, 10, 3))
    assert res["next_paycheck"]["date"] == date(2026, 10, 16)
    assert res["next_paycheck"]["amount_cents"] == 600_000  # face, not smoothed
    assert res["next_paycheck"]["days_away"] == 13
    assert [e["name"] for e in res["before"]] == ["Loan A", "Loan B"]
    assert res["before_total_cents"] == 30_000
    assert [e["name"] for e in res["on_payday"]] == ["Loan C"]
    assert res["on_payday_total_cents"] == 30_000


def test_a_paycheck_landing_today_counts_as_received(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in",
          frequency="biweekly", day_of_week=5, week_anchor=date(2026, 10, 2))
    _item(db, name="Today's loan", amount_cents=10_000, day_of_month=2)
    res = until_next_paycheck(db, date(2026, 10, 2))
    assert res["next_paycheck"]["date"] == date(2026, 10, 16)  # not today's
    assert [e["name"] for e in res["before"]] == ["Today's loan"]


def test_window_spans_a_month_boundary(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=5)
    _item(db, name="Late-month loan", amount_cents=10_000, day_of_month=28)
    _item(db, name="Early-month loan", amount_cents=20_000, day_of_month=2)
    res = until_next_paycheck(db, date(2026, 9, 25))  # next paycheck Oct 5
    assert [e["name"] for e in res["before"]] == ["Late-month loan", "Early-month loan"]
    assert res["before_total_cents"] == 30_000


def test_loans_respect_their_start_and_end_months(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=15)
    _item(db, name="Ended", amount_cents=10_000, day_of_month=10, end_month="2026-09")
    _item(db, name="Live", amount_cents=20_000, day_of_month=10, end_month="2026-10")
    _item(db, name="Not yet", amount_cents=40_000, day_of_month=10, start_month="2026-11")
    res = until_next_paycheck(db, date(2026, 10, 1))
    assert [e["name"] for e in res["before"]] == ["Live"]


def test_whose_paycheck_can_be_chosen(db):
    evan, rach = _person(db, "Evan"), _person(db, "Rach")
    _item(db, name="Evan pay", amount_cents=600_000, direction="in", person_id=evan.id,
          frequency="biweekly", day_of_week=5, week_anchor=date(2026, 10, 2))
    _item(db, name="Rach pay", amount_cents=400_000, direction="in", person_id=rach.id,
          frequency="biweekly", day_of_week=5, week_anchor=date(2026, 9, 25))
    assert until_next_paycheck(db, date(2026, 10, 2))["next_paycheck"]["name"] == "Rach pay"  # Oct 9
    assert until_next_paycheck(db, date(2026, 10, 2), person_id=evan.id)["next_paycheck"]["name"] == "Evan pay"  # Oct 16


def test_one_off_transactions_in_the_window_count(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=15)
    db.add(models.Transaction(date=date(2026, 10, 8), description="Couch", amount_cents=50_000, direction="out"))
    db.add(models.Transaction(date=date(2026, 10, 20), description="Later", amount_cents=70_000, direction="out"))
    db.commit()
    res = until_next_paycheck(db, date(2026, 10, 1))
    assert [(e["name"], e["kind"]) for e in res["before"]] == [("Couch", "transaction")]


def test_undated_items_are_reported_not_silently_dropped(db):
    _item(db, name="Paycheck", amount_cents=600_000, direction="in", day_of_month=15)
    _item(db, name="Electric", amount_cents=20_000)  # monthly, no day
    _item(db, name="Gym", amount_cents=5_000, frequency="weekly")  # weekly, no weekday
    _item(db, name="Ended elsewhere", amount_cents=1, end_month="2026-01")
    res = until_next_paycheck(db, date(2026, 10, 1))
    assert sorted(u["name"] for u in res["undated"]) == ["Electric", "Gym"]
    assert res["before_total_cents"] == 0


def test_no_dated_income_means_no_answer(db):
    _item(db, name="Loan", amount_cents=10_000, day_of_month=5)
    res = until_next_paycheck(db, date(2026, 10, 1))
    assert res["next_paycheck"] is None
    assert res["before"] == []
