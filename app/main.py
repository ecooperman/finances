import subprocess
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from shared_python import accounts_gate, oidc_login, owned

from . import access, config, crud, schemas
from .config import SHARED_ASSETS_BASE
from .routers import (
    balance,
    categories,
    daily,
    deferrals,
    funds,
    linked_lists,
    monthly,
    paycheck,
    people,
    recurring,
    scenarios,
    transactions,
    trips,
    users,
)

# Schema is owned by Alembic migrations (see migrations/) - run
# `alembic upgrade head` before starting the app rather than relying on
# create_all, so schema changes never silently bypass migrations. (A new
# account's default categories are made when the account is, see crud.py.)


def _get_git_sha() -> str:
    """Short commit hash the running app was deployed from, read straight
    from the repo on disk (the deploy pulls a real git checkout) - no CI
    wiring needed, and it can never drift from what's actually running.
    """
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


GIT_SHA = _get_git_sha()

app = FastAPI(title="Finances")
access.install(app)  # only people with an account get in, each inside their own private finances (app/access.py)
templates = Jinja2Templates(directory="templates")


@app.get("/api/version")
def get_version():
    return {"version": GIT_SHA}


@app.exception_handler(crud.BadReference)
def _bad_reference(request: Request, exc: crud.BadReference):
    return JSONResponse({"detail": str(exc)}, status_code=400, headers={"Cache-Control": "no-store"})


@app.exception_handler(owned.WrongOwner)
def _wrong_owner(request: Request, exc: owned.WrongOwner):
    """The data layer's last line of defence refused a write that touched someone else's data."""
    return JSONResponse({"detail": "That isn't yours to change"}, status_code=403, headers={"Cache-Control": "no-store"})


@app.get("/api/me", response_model=schemas.Me)
def get_me(request: Request, account=Depends(accounts_gate.current_account)):
    """Who is signed in, for the page header's email and Log out (the shared Global.mountUserBadge reads this), and for
    hiding what only an administrator may use: the trip forecast and linked lists read the administrator's own trips and
    lists apps, so they are theirs alone."""
    return schemas.Me(
        id=account.id,
        email=account.email,
        is_admin=account.is_admin,
        can_use={"trips": account.is_admin, "lists": account.is_admin},
        logout_url=oidc_login.logout_url(request),
    )


# Each HTML page is a Jinja2 template rendered by an explicit route (not
# served via StaticFiles) so shared_assets_base can be baked in server-side
# - no client-side fetch, no flash of unstyled content. See config.py's
# SHARED_ASSETS_BASE for how local vs. production is decided. Registered
# before the StaticFiles mount below so these take priority over it.
def _render(name: str):
    def route(request: Request):
        return templates.TemplateResponse(
            request, name, {"shared_assets_base": SHARED_ASSETS_BASE}
        )

    return route


app.get("/", response_class=HTMLResponse)(_render("index.html"))
app.get("/budget.html", response_class=HTMLResponse)(_render("budget.html"))
app.get("/scenarios.html", response_class=HTMLResponse)(_render("scenarios.html"))
app.get("/settings.html", response_class=HTMLResponse)(_render("settings.html"))
app.get("/users.html", response_class=HTMLResponse)(_render("users.html"))


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """Never let the browser (or iOS's aggressive standalone-PWA cache) serve
    a stale copy of the app - these are private tools, not public
    sites, so there's no real cost to always fetching fresh. `no-store` (not
    `no-cache`) is deliberate: `no-cache` still permits caching as long as
    the cache revalidates first, which a CDN or PWA cache layer isn't
    obligated to actually do - `no-store` is the only unambiguous "never
    cache this, anywhere" signal. See static/version.js, which surfaces
    GIT_SHA in a corner of every page so a deploy landing (vs. a stale
    cached copy) is something you can actually verify by eye.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(people.router)
app.include_router(categories.router)
app.include_router(recurring.router)
app.include_router(transactions.router)
app.include_router(funds.router)
app.include_router(trips.router)
app.include_router(linked_lists.router)
app.include_router(scenarios.router)
app.include_router(monthly.router)
app.include_router(paycheck.router)
app.include_router(deferrals.router)
app.include_router(daily.router)
app.include_router(balance.router)
app.include_router(users.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    from .config import HOST, PORT

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
