"""Pydantic schemas.

Money crosses the API as `amount_cents` (integer) in both directions - the
frontend converts to/from dollars at the input/display boundary only, so the
wire format stays exact and symmetric (a PATCH can echo back what a GET
returned untouched).
"""

# `date` is aliased because the Transaction schemas have a field literally
# named `date`; `date: Optional[date] = None` would otherwise rebind the
# name to None before the annotation is evaluated (CPython stores the value
# first), leaving the field typed as None-only. See TransactionUpdate.
from datetime import date as date_type, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Direction = Literal["in", "out"]
Frequency = Literal["weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]
AdjustmentKind = Literal["add", "remove", "modify"]
# Only these need an anchor_month (they land in specific calendar months);
# weekly/biweekly/monthly land every month.
SUBMONTHLY_FREQUENCIES = {"quarterly", "semiannual", "annual"}
AddKind = Literal["recurring", "fund"]
FundEntryUnit = Literal["year", "month", "weeks", "months", "times_year"]


def _positive_cents(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    if v <= 0:
        raise ValueError("amount_cents must be a positive whole number of cents")
    return v


def _valid_month_str(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    try:
        datetime.strptime(v, "%Y-%m")
    except ValueError:
        raise ValueError("month must be 'YYYY-MM'")
    return v


def _valid_anchor_month(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    if not 1 <= v <= 12:
        raise ValueError("anchor_month must be 1-12")
    return v


def _valid_day_of_week(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    if not 0 <= v <= 6:
        raise ValueError("day_of_week must be 0 (Sunday) .. 6 (Saturday)")
    return v


def _blank_to_none(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


class PersonBase(BaseModel):
    name: str
    color: str = "#888888"


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class Person(PersonBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class CategoryBase(BaseModel):
    name: str
    color: str = "#8a8f98"
    text_color: Literal["dark", "light"] = "dark"


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    text_color: Optional[Literal["dark", "light"]] = None
    sort_order: Optional[int] = None


class Category(CategoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sort_order: int


class CategoryReorderRequest(BaseModel):
    ordered_ids: List[int]


# ---------------------------------------------------------------------------
# Recurring items
# ---------------------------------------------------------------------------


class RecurringItemBase(BaseModel):
    name: str
    amount_cents: int
    direction: Direction
    frequency: Frequency = "monthly"
    anchor_month: Optional[int] = None
    day_of_month: Optional[int] = None
    day_of_week: Optional[int] = None  # 0=Sun..6=Sat, for weekly/biweekly
    week_anchor: Optional[date_type] = None  # a real date, for biweekly phase
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    active: bool = True
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    notes: Optional[str] = None
    reference_id: Optional[str] = None  # provider ref for a BNPL plan; unique

    _check_amount = field_validator("amount_cents")(_positive_cents)
    _check_anchor = field_validator("anchor_month")(_valid_anchor_month)
    _check_dow = field_validator("day_of_week")(_valid_day_of_week)
    _check_start = field_validator("start_month")(_valid_month_str)
    _check_end = field_validator("end_month")(_valid_month_str)
    _check_ref = field_validator("reference_id")(_blank_to_none)

    @model_validator(mode="after")
    def _anchor_required_for_submonthly(self):
        if self.frequency in SUBMONTHLY_FREQUENCIES and self.anchor_month is None:
            raise ValueError("anchor_month is required for quarterly / semi-annual / annual")
        return self


class RecurringItemCreate(RecurringItemBase):
    pass


class RecurringItemUpdate(BaseModel):
    name: Optional[str] = None
    amount_cents: Optional[int] = None
    direction: Optional[Direction] = None
    frequency: Optional[Frequency] = None
    anchor_month: Optional[int] = None
    day_of_month: Optional[int] = None
    day_of_week: Optional[int] = None
    week_anchor: Optional[date_type] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    active: Optional[bool] = None
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    notes: Optional[str] = None
    reference_id: Optional[str] = None

    _check_amount = field_validator("amount_cents")(_positive_cents)
    _check_anchor = field_validator("anchor_month")(_valid_anchor_month)
    _check_dow = field_validator("day_of_week")(_valid_day_of_week)
    _check_start = field_validator("start_month")(_valid_month_str)
    _check_end = field_validator("end_month")(_valid_month_str)
    _check_ref = field_validator("reference_id")(_blank_to_none)


class RecurringItem(RecurringItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: Optional[Category] = None
    person: Optional[Person] = None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionBase(BaseModel):
    date: date_type
    description: str
    amount_cents: int
    direction: Direction
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    notes: Optional[str] = None
    account_name: Optional[str] = None
    fund_id: Optional[int] = None

    _check_amount = field_validator("amount_cents")(_positive_cents)


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    date: Optional[date_type] = None
    description: Optional[str] = None
    amount_cents: Optional[int] = None
    direction: Optional[Direction] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    notes: Optional[str] = None
    account_name: Optional[str] = None
    fund_id: Optional[int] = None

    _check_amount = field_validator("amount_cents")(_positive_cents)


class Transaction(TransactionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    pending: bool
    category: Optional[Category] = None
    person: Optional[Person] = None


# Converting between the two kinds: the shared fields (name/amount/
# direction/category/person/notes) carry over untouched; these bodies only
# supply what the target kind needs that the source doesn't have.


class ConvertToRecurring(BaseModel):
    frequency: Frequency = "monthly"
    anchor_month: Optional[int] = None
    day_of_month: Optional[int] = None
    start_month: Optional[str] = None
    end_month: Optional[str] = None

    _check_anchor = field_validator("anchor_month")(_valid_anchor_month)
    _check_start = field_validator("start_month")(_valid_month_str)
    _check_end = field_validator("end_month")(_valid_month_str)

    @model_validator(mode="after")
    def _anchor_required_for_submonthly(self):
        if self.frequency in SUBMONTHLY_FREQUENCIES and self.anchor_month is None:
            raise ValueError("anchor_month is required for quarterly / semi-annual / annual")
        return self


class ConvertToTransaction(BaseModel):
    date: date_type


# ---------------------------------------------------------------------------
# Sinking funds
# ---------------------------------------------------------------------------


def _entry_period_needed(obj):
    if obj.entry_unit in ("weeks", "months", "times_year") and not obj.entry_period_n:
        raise ValueError("entry_period_n is required for that entry unit")
    return obj


class FundBase(BaseModel):
    name: str
    annual_amount_cents: int  # canonical rate; monthly set-aside = round(/12)
    # How the rate was typed, so the form shows it back the same way.
    entry_amount_cents: Optional[int] = None
    entry_unit: Optional[FundEntryUnit] = None
    entry_period_n: Optional[int] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    start_month: Optional[str] = None  # server defaults to the creation month
    active: bool = True
    notes: Optional[str] = None

    _check_amount = field_validator("annual_amount_cents")(_positive_cents)
    _check_start = field_validator("start_month")(_valid_month_str)

    @model_validator(mode="after")
    def _check_entry(self):
        return _entry_period_needed(self)


class FundCreate(FundBase):
    pass


class FundUpdate(BaseModel):
    name: Optional[str] = None
    annual_amount_cents: Optional[int] = None
    entry_amount_cents: Optional[int] = None
    entry_unit: Optional[FundEntryUnit] = None
    entry_period_n: Optional[int] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    start_month: Optional[str] = None
    active: Optional[bool] = None
    notes: Optional[str] = None

    _check_amount = field_validator("annual_amount_cents")(_positive_cents)
    _check_start = field_validator("start_month")(_valid_month_str)

    @model_validator(mode="after")
    def _check_entry(self):
        return _entry_period_needed(self)


class Fund(FundBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: Optional[Category] = None
    person: Optional[Person] = None


class FundWithStatus(Fund):
    # Filled by the router from services.funds.fund_status.
    monthly_contribution_cents: int
    accrued_cents: int
    spent_cents: int
    balance_cents: int
    spent_ytd_cents: int


class FundsSummary(BaseModel):
    active_count: int
    monthly_total_cents: int
    banked_total_cents: int


# ---------------------------------------------------------------------------
# Trip cost forecast (cost read live from the trip-planning app)
# ---------------------------------------------------------------------------


class TripForecastRow(BaseModel):
    trip_id: int
    name: str
    trip_month: Optional[str] = None  # "YYYY-MM"; None = no date set in trip-planning
    total_cents: int  # what's forecast (override if set, else computed)
    computed_total_cents: int  # trip-planning's activities + booked stays
    override_amount_cents: Optional[int] = None
    monthly_contribution_cents: int  # total spread over months_remaining
    months_remaining: Optional[int] = None
    excluded: bool = False
    settled_at: Optional[str] = None


class TripForecasts(BaseModel):
    upcoming: List[TripForecastRow] = []
    no_date: List[TripForecastRow] = []
    excluded: List[TripForecastRow] = []


class TripSettlementUpdate(BaseModel):
    excluded: Optional[bool] = None
    override_amount_cents: Optional[int] = None
    note: Optional[str] = None

    _check_override = field_validator("override_amount_cents")(_positive_cents)


class SettleTripRequest(BaseModel):
    date: date_type
    amount_cents: Optional[int] = None  # defaults to the trip's forecast total

    _check_amount = field_validator("amount_cents")(_positive_cents)


class TripsSummary(BaseModel):
    upcoming_count: int
    monthly_total_cents: int


# ---------------------------------------------------------------------------
# "Until the next paycheck" lookahead
# ---------------------------------------------------------------------------


class DatedPayment(BaseModel):
    date: date_type
    name: str
    amount_cents: int  # the real per-payment amount, not smoothed
    kind: Literal["recurring", "transaction", "carryover"]


class UndatedItem(BaseModel):
    name: str
    amount_cents: int
    frequency: str


class NextPaycheck(BaseModel):
    date: date_type
    name: str
    amount_cents: int
    days_away: int


class UntilPaycheck(BaseModel):
    as_of: date_type
    next_paycheck: Optional[NextPaycheck] = None
    before: List[DatedPayment] = []  # money out from today up to the day before payday
    before_total_cents: int = 0
    on_payday: List[DatedPayment] = []  # money out dated the paycheck day itself
    on_payday_total_cents: int = 0
    undated: List[UndatedItem] = []  # recurring money-out we couldn't place on a date


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _check_adjustment_shape(obj):
    """Per-`kind` required-field rules, shared by the create and update
    schemas (both carry the full adjustment body). A remove/modify targets
    either a recurring item (`target_recurring_id`) or a fund
    (`target_fund_id`) - exactly one."""
    if obj.kind == "add":
        if obj.add_kind == "fund":
            missing = [f for f in ("name", "amount_cents") if getattr(obj, f) is None]
            if missing:
                raise ValueError(f"'add' fund requires: {', '.join(missing)}")
        else:
            missing = [f for f in ("name", "amount_cents", "direction") if getattr(obj, f) is None]
            if missing:
                raise ValueError(f"'add' adjustment requires: {', '.join(missing)}")
            if obj.frequency in SUBMONTHLY_FREQUENCIES and obj.anchor_month is None:
                raise ValueError("anchor_month is required for quarterly / semi-annual / annual 'add' adjustments")
        return obj

    has_recurring = obj.target_recurring_id is not None
    has_fund = obj.target_fund_id is not None
    if has_recurring == has_fund:
        raise ValueError(
            f"'{obj.kind}' adjustment requires exactly one of "
            "target_recurring_id / target_fund_id"
        )
    if obj.kind == "modify":
        has_mult = obj.multiplier is not None
        has_override = obj.override_amount_cents is not None
        if has_mult == has_override:
            raise ValueError(
                "'modify' adjustment requires exactly one of multiplier / override_amount_cents"
            )
        if has_mult and obj.multiplier < 0:
            raise ValueError("multiplier must be >= 0")
    return obj


class ScenarioAdjustmentCreate(BaseModel):
    kind: AdjustmentKind
    # "add" fields. add_kind picks recurring line vs. sinking fund; for a
    # fund, amount_cents is the annual rate and direction/frequency are unused.
    add_kind: AddKind = "recurring"
    name: Optional[str] = None
    amount_cents: Optional[int] = None
    direction: Optional[Direction] = None
    frequency: Optional[Frequency] = "monthly"
    anchor_month: Optional[int] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    # "remove" / "modify" fields - target exactly one of these
    target_recurring_id: Optional[int] = None
    target_fund_id: Optional[int] = None
    multiplier: Optional[float] = None
    override_amount_cents: Optional[int] = None
    notes: Optional[str] = None

    _check_anchor = field_validator("anchor_month")(_valid_anchor_month)
    _check_amount = field_validator("amount_cents")(_positive_cents)
    _check_override = field_validator("override_amount_cents")(_positive_cents)

    @model_validator(mode="after")
    def _validate_shape(self):
        return _check_adjustment_shape(self)


# A full replace of the adjustment body is simplest given the per-kind shape
# rules - the frontend re-submits every field it knows.
class ScenarioAdjustmentUpdate(ScenarioAdjustmentCreate):
    pass


class ScenarioAdjustment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scenario_id: int
    kind: str
    add_kind: str = "recurring"
    name: Optional[str] = None
    amount_cents: Optional[int] = None
    direction: Optional[str] = None
    frequency: Optional[str] = None
    anchor_month: Optional[int] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    target_recurring_id: Optional[int] = None
    target_fund_id: Optional[int] = None
    multiplier: Optional[float] = None
    override_amount_cents: Optional[int] = None
    notes: Optional[str] = None
    category: Optional[Category] = None
    person: Optional[Person] = None
    target_recurring: Optional[RecurringItem] = None
    target_fund: Optional[Fund] = None


class ScenarioBase(BaseModel):
    name: str
    notes: Optional[str] = None


class ScenarioCreate(ScenarioBase):
    pass


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None


class Scenario(ScenarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    adjustments: List[ScenarioAdjustment] = []


# ---------------------------------------------------------------------------
# Monthly view (the aggregation endpoint's response)
# ---------------------------------------------------------------------------


class MonthRow(BaseModel):
    kind: Literal["recurring", "transaction", "fund", "trip", "carryover"]
    id: int
    name: str
    amount_cents: int
    direction: Direction
    frequency: Optional[str] = None
    day: Optional[int] = None
    # Per-payment amount (what actually leaves/arrives each time), vs
    # amount_cents which is this month's smoothed contribution. And, for
    # weekly/biweekly with a weekday set, the real days of the month it pays
    # on - the calendar draws one entry per day at the face amount.
    face_amount_cents: Optional[int] = None
    occurrence_days: Optional[List[int]] = None
    # Line-item details shown when you click a day on the calendar.
    notes: Optional[str] = None
    reference_id: Optional[str] = None
    account_name: Optional[str] = None
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    day_of_week: Optional[int] = None  # 0=Sun..6=Sat, weekly/biweekly
    category: Optional[Category] = None
    person: Optional[Person] = None
    # "normal" for real rows; "added"/"removed"/"modified" when a scenario
    # is applied so the UI can tint them.
    effect: Literal["normal", "added", "removed", "modified", "deferred"] = "normal"
    original_amount_cents: Optional[int] = None
    # Payment deferrals ("couldn't pay this month"). effect="deferred" rows
    # carry `deferral_id` (to undo) and `deferred_to` (the month it rolled
    # into). kind="carryover" rows are last month's unpaid items: `carried_from`
    # is the month first due, `carry_source_id` the deferral to carry again.
    deferral_id: Optional[int] = None
    deferred_to: Optional[str] = None
    carried_from: Optional[str] = None
    carry_source_id: Optional[int] = None


class MonthTotals(BaseModel):
    in_cents: int
    out_cents: int
    net_cents: int


class MonthSide(BaseModel):
    money_in: List[MonthRow]
    money_out: List[MonthRow]
    totals: MonthTotals
    normalized: MonthTotals


class ScenarioMonthResult(MonthSide):
    id: int
    name: str
    delta: MonthTotals  # cash-flow change vs. the real month
    normalized_delta: MonthTotals  # provisioning change (where fund adjustments land)


class MonthResult(MonthSide):
    month: str
    scenario: Optional[ScenarioMonthResult] = None


# --- payment deferrals ("couldn't pay this month") -----------------------


class DeferralCreate(BaseModel):
    """Defer a recurring item's payment in a month (`recurring_item_id` +
    `month`), defer a one-off (`transaction_id`), or carry an already-carried
    line forward again (`origin_id`). Exactly one of the three."""

    recurring_item_id: Optional[int] = None
    month: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    transaction_id: Optional[int] = None
    origin_id: Optional[int] = None

    @model_validator(mode="after")
    def _one_form(self):
        forms = [
            self.recurring_item_id is not None and self.month is not None,
            self.transaction_id is not None and self.recurring_item_id is None,
            self.origin_id is not None,
        ]
        if sum(forms) != 1 or (self.month is not None and self.recurring_item_id is None):
            raise ValueError(
                "give exactly one of: recurring_item_id + month, transaction_id, origin_id"
            )
        return self


class DeferralOut(BaseModel):
    id: int
    recurring_item_id: Optional[int] = None
    transaction_id: Optional[int] = None
    month: str
    original_month: str
    amount_cents: int
    origin_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
