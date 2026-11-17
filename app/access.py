"""Who may use this app, and whose finances they see.

Several people can have an account, each with completely private finances. This is the household budget, so the bar is
high: nobody can read or change another person's money, and no request can ask its way past that.

* Default-deny. Signing in is not enough: an administrator adds a person on the Users page, or, for an administrator, the
  account is made on their first sign-in (taking over the data that existed before accounts).
* shared_python.accounts_gate wraps the WHOLE app, so every page, API route and file refuses anyone without an account, and
  runs each request inside that person's scope: every database read and write is filtered to them below the routes' own code,
  a write that would put a row in someone else's name or point it at someone else's row is refused (shared_python.owned),
  and every route also checks any id it is handed belongs to the caller.
* What reads the ADMINISTRATOR's other apps is for administrators only. The trip forecast and the linked lists reach the
  trips and lists apps with service tokens that see the administrator's data, so for anyone else they return nothing, whatever
  is asked (app/integrations.py).

Nothing calls this app (it calls trips and lists, on this machine, with their service tokens), so there is no
machine-to-machine exception and nothing is public: no manifest, no icons, no service worker."""
from typing import Union

from shared_python import accounts_gate
from shared_python.accounts_gate import Account

from . import config, crud, integrations, models
from .database import SessionLocal

def account_for(email: str) -> Union[Account, str]:
    """This person's account in the app: administrators always have one (made on first sign-in), anyone else only
    if an administrator let them in and has not since removed them."""
    is_admin = email in config.ADMIN_EMAILS
    with SessionLocal() as db:
        user = crud.get_user_by_email(db, email)
        if user is None:
            if not is_admin:
                return "none"
            user = crud.adopt_or_create_admin(db, email)
        if user.status != models.USER_ACTIVE and not is_admin:
            return "removed"
        return Account(id=user.id, email=user.email, is_admin=is_admin)


def install(app) -> None:
    @app.middleware("http")
    async def administrators_reach_other_apps(request, call_next):
        # Registered BEFORE the gate, so it runs inside it, after the person's account is known.
        account = getattr(request.state, "account", None)
        token = integrations.set_allowed(account is not None and account.is_admin)
        try:
            return await call_next(request)
        finally:
            integrations.reset(token)

    accounts_gate.install(app, account_for=account_for, dev_user_email=config.DEV_USER_EMAIL)
