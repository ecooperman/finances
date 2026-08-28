"""SQLAlchemy models for the family finances tracker.

Design notes:
- Money is stored as an integer number of cents (`amount_cents`) everywhere,
  never a float - the API layer converts to/from decimal dollars. This keeps
  arithmetic exact and dodges SQLite's float storage entirely.
- Enum-like fields (`direction`, `frequency`, adjustment `kind`) are plain
  String columns validated in the Pydantic layer, not `sa.Enum` - SQLite
  can't ALTER a CHECK/enum constraint in place, so a String keeps the door
  open for adding new values later without a table rebuild.
- `person_id` being NULL means "joint / whole household" rather than
  attributed to one person.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base

# Allowed values for the String "enum" columns - enforced in schemas.py.
DIRECTIONS = ("in", "out")
FREQUENCIES = ("monthly", "quarterly", "semiannual", "annual")
# How many months apart each cadence repeats (drives both which months a
# non-monthly item lands in and the "normalized to per-month" figure).
FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}
ADJUSTMENT_KINDS = ("add", "remove", "modify")
# How a sinking fund's contribution rate was entered - stored so the form
# round-trips. `annual_amount_cents` is always the derived canonical value.
FUND_ENTRY_UNITS = ("year", "month", "weeks", "months", "times_year")


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    color = Column(String, nullable=False, default="#888888")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    color = Column(String, nullable=False, default="#8a8f98")
    # "dark" or "light" - which text color reads legibly on top of `color`.
    text_color = Column(String, nullable=False, default="dark", server_default="dark")
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecurringItem(Base):
    """A known, repeating cash flow - a salary, the mortgage, HOA dues, a
    quarterly insurance premium. The "knowns" that make up the monthly
    baseline before any one-off activity.
    """

    __tablename__ = "recurring_items"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    direction = Column(String, nullable=False)  # "in" | "out"
    frequency = Column(String, nullable=False, default="monthly")

    # For non-monthly items: 1-12, the first calendar month the item lands
    # in. Subsequent hits are anchor_month + N * FREQUENCY_MONTHS[frequency].
    # Ignored for monthly items.
    anchor_month = Column(Integer, nullable=True)
    # Purely informational - which day of the month it hits, for display and
    # row ordering. Not used in any math.
    day_of_month = Column(Integer, nullable=True)

    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="SET NULL"), nullable=True)

    active = Column(Boolean, nullable=False, default=True)
    # Inclusive "YYYY-MM" bounds; NULL means unbounded on that side.
    start_month = Column(String, nullable=True)
    end_month = Column(String, nullable=True)

    notes = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", lazy="joined")
    person = relationship("Person", lazy="joined")


class Transaction(Base):
    """A one-off, dated cash flow worth recording - the ad-hoc things that
    "move the needle" (a big purchase, a bonus, a tax refund). Deliberately
    not meant for tracking every $10 coffee.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        # Dedup key for imported rows (see `source`); NULLs (manual entries)
        # don't collide under SQLite's NULL-distinct semantics.
        UniqueConstraint("source", "external_id", name="uq_transaction_source_external"),
    )

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    description = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    direction = Column(String, nullable=False)  # "in" | "out"

    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="SET NULL"), nullable=True)

    notes = Column(String, nullable=True)

    # Optional: this one-off spend is drawn from a sinking fund. It still
    # counts as real cash flow; it also draws down that fund's balance.
    fund_id = Column(Integer, ForeignKey("funds.id", ondelete="SET NULL"), nullable=True)

    # Import plumbing - unused by v1 (everything is "manual") but present now
    # so the phase-2 SimpleFIN sync doesn't need a schema migration on these.
    source = Column(String, nullable=False, default="manual")
    external_id = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    pending = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", lazy="joined")
    person = relationship("Person", lazy="joined")
    fund = relationship("SinkingFund", lazy="joined")


class SinkingFund(Base):
    """Money set aside every month for a cost you know is coming but can't
    schedule - vet visits, dog grooming, car repairs, gifts. Contributes
    `annual_amount_cents / 12` to the monthly *provisioning* total (never
    cash flow), and carries a running balance = (accrued since start_month)
    minus (fund-tagged transactions), rolling over across years.
    """

    __tablename__ = "funds"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    # Canonical contribution rate. Monthly set-aside = round(/12).
    annual_amount_cents = Column(Integer, nullable=False)

    # How the user typed the rate, so the form can show it back the same way.
    # entry_unit in FUND_ENTRY_UNITS; entry_period_n is the N for
    # "every N weeks" / "every N months" / "N times per year".
    entry_amount_cents = Column(Integer, nullable=True)
    entry_unit = Column(String, nullable=True)
    entry_period_n = Column(Integer, nullable=True)

    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="SET NULL"), nullable=True)

    # "YYYY-MM" - accrual starts here (defaults to the creation month).
    start_month = Column(String, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    notes = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", lazy="joined")
    person = relationship("Person", lazy="joined")


class Scenario(Base):
    """A saved "what-if" - a named bundle of adjustments layered over the
    real recurring items at query time. Nothing here ever mutates a
    RecurringItem or Transaction row.
    """

    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    notes = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    adjustments = relationship(
        "ScenarioAdjustment",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class ScenarioAdjustment(Base):
    """One tweak within a Scenario. `kind` picks which columns matter:

    - "add":    name, amount_cents, direction, frequency, anchor_month,
                category_id, person_id  (a brand-new hypothetical line);
                or, when add_kind="fund": name, amount_cents (annual),
                category_id, person_id  (a hypothetical sinking fund)
    - "remove": target_recurring_id OR target_fund_id  (pretend it's gone)
    - "modify": (target_recurring_id OR target_fund_id) + exactly one of
                multiplier / override_amount_cents  (scale or replace)

    Recurring/one-off adjustments hit the cash-flow figure; fund adjustments
    hit the provisioning figure only.
    """

    __tablename__ = "scenario_adjustments"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)  # "add" | "remove" | "modify"
    # For kind="add": "recurring" (default) or "fund".
    add_kind = Column(String, nullable=False, default="recurring", server_default="recurring")

    # --- "add" columns ---
    name = Column(String, nullable=True)
    amount_cents = Column(Integer, nullable=True)
    direction = Column(String, nullable=True)
    frequency = Column(String, nullable=True, default="monthly")
    anchor_month = Column(Integer, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="SET NULL"), nullable=True)

    # --- "remove" / "modify" columns ---
    target_recurring_id = Column(
        Integer, ForeignKey("recurring_items.id", ondelete="CASCADE"), nullable=True
    )
    target_fund_id = Column(Integer, ForeignKey("funds.id", ondelete="CASCADE"), nullable=True)
    multiplier = Column(Float, nullable=True)
    override_amount_cents = Column(Integer, nullable=True)

    notes = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenario = relationship("Scenario", back_populates="adjustments")
    category = relationship("Category", lazy="joined")
    person = relationship("Person", lazy="joined")
    target_recurring = relationship("RecurringItem", lazy="joined")
    target_fund = relationship("SinkingFund", lazy="joined")
