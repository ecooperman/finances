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

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Direction = Literal["in", "out"]
Frequency = Literal["monthly", "quarterly", "semiannual", "annual"]
AdjustmentKind = Literal["add", "remove", "modify"]


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
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    active: bool = True
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    notes: Optional[str] = None

    _check_amount = field_validator("amount_cents")(_positive_cents)
    _check_anchor = field_validator("anchor_month")(_valid_anchor_month)
    _check_start = field_validator("start_month")(_valid_month_str)
    _check_end = field_validator("end_month")(_valid_month_str)

    @model_validator(mode="after")
    def _anchor_required_for_non_monthly(self):
        if self.frequency != "monthly" and self.anchor_month is None:
            raise ValueError("anchor_month is required for non-monthly frequencies")
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
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    active: Optional[bool] = None
    start_month: Optional[str] = None
    end_month: Optional[str] = None
    notes: Optional[str] = None

    _check_amount = field_validator("amount_cents")(_positive_cents)
    _check_anchor = field_validator("anchor_month")(_valid_anchor_month)
    _check_start = field_validator("start_month")(_valid_month_str)
    _check_end = field_validator("end_month")(_valid_month_str)


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
    def _anchor_required_for_non_monthly(self):
        if self.frequency != "monthly" and self.anchor_month is None:
            raise ValueError("anchor_month is required for non-monthly frequencies")
        return self


class ConvertToTransaction(BaseModel):
    date: date_type


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _check_adjustment_shape(obj):
    """Per-`kind` required-field rules, shared by the create and update
    schemas (both carry the full adjustment body)."""
    if obj.kind == "add":
        missing = [f for f in ("name", "amount_cents", "direction") if getattr(obj, f) is None]
        if missing:
            raise ValueError(f"'add' adjustment requires: {', '.join(missing)}")
        if obj.frequency and obj.frequency != "monthly" and obj.anchor_month is None:
            raise ValueError("anchor_month is required for non-monthly 'add' adjustments")
    elif obj.kind == "remove":
        if obj.target_recurring_id is None:
            raise ValueError("'remove' adjustment requires target_recurring_id")
    elif obj.kind == "modify":
        if obj.target_recurring_id is None:
            raise ValueError("'modify' adjustment requires target_recurring_id")
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
    # "add" fields
    name: Optional[str] = None
    amount_cents: Optional[int] = None
    direction: Optional[Direction] = None
    frequency: Optional[Frequency] = "monthly"
    anchor_month: Optional[int] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    # "remove" / "modify" fields
    target_recurring_id: Optional[int] = None
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
    name: Optional[str] = None
    amount_cents: Optional[int] = None
    direction: Optional[str] = None
    frequency: Optional[str] = None
    anchor_month: Optional[int] = None
    category_id: Optional[int] = None
    person_id: Optional[int] = None
    target_recurring_id: Optional[int] = None
    multiplier: Optional[float] = None
    override_amount_cents: Optional[int] = None
    notes: Optional[str] = None
    category: Optional[Category] = None
    person: Optional[Person] = None
    target_recurring: Optional[RecurringItem] = None


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
    kind: Literal["recurring", "transaction"]
    id: int
    name: str
    amount_cents: int
    direction: Direction
    frequency: Optional[str] = None
    day: Optional[int] = None
    category: Optional[Category] = None
    person: Optional[Person] = None
    # "normal" for real rows; "added"/"removed"/"modified" when a scenario
    # is applied so the UI can tint them.
    effect: Literal["normal", "added", "removed", "modified"] = "normal"
    original_amount_cents: Optional[int] = None


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
    delta: MonthTotals


class MonthResult(MonthSide):
    month: str
    scenario: Optional[ScenarioMonthResult] = None
