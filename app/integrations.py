"""Whether the code that reaches the ADMINISTRATOR's other apps (trips, lists) may run right now.

Those calls use service tokens that see the administrator's data, whoever is asking, so they must never happen for
anyone else. This is a tiny module of its own (no imports from the app) so both the gate (app/access.py, which sets it)
and the services (which check it) can use it without importing each other."""
from contextvars import ContextVar

# True only while an administrator's request runs; anything else (another person, a script, a background task) is False.
_allowed: ContextVar = ContextVar("finances_integrations", default=False)


def allowed() -> bool:
    return _allowed.get()


def set_allowed(value: bool):
    """Returns the token to hand back to `reset`."""
    return _allowed.set(bool(value))


def reset(token) -> None:
    _allowed.reset(token)
