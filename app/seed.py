"""What a new account starts with: the usual budget categories (and nothing else; their own people, items and amounts are
theirs to add)."""
from sqlalchemy.orm import Session

from . import models

# (name, color, text color that reads on it)
DEFAULT_CATEGORIES = [
    ("Income", "#2b6f5c", "light"),
    ("Housing", "#3a6ea5", "light"),
    ("Utilities", "#4c8f8b", "light"),
    ("Insurance", "#8a6d3b", "light"),
    ("Transportation", "#b5651d", "light"),
    ("Groceries", "#5a9e42", "light"),
    ("Dining", "#c9803f", "light"),
    ("Healthcare", "#c05555", "light"),
    ("Childcare", "#9a6fb0", "light"),
    ("Debt", "#7a4a4a", "light"),
    ("Savings & Investments", "#3f7d5c", "light"),
    ("Discretionary", "#8f7fb0", "light"),
    ("Other", "#8a8f98", "light"),
]


def seed_categories(db: Session) -> None:
    """Give the person in scope the default categories, if they have none."""
    if db.query(models.Category).count() == 0:
        for i, (name, color, text_color) in enumerate(DEFAULT_CATEGORIES):
            db.add(models.Category(name=name, color=color, text_color=text_color, sort_order=(i + 1) * 10))
        db.commit()
