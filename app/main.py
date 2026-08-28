import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import SHARED_ASSETS_BASE
from .routers import categories, monthly, people, recurring, scenarios, transactions

# Schema is owned by Alembic migrations (see migrations/) - run
# `alembic upgrade head` before starting the app rather than relying on
# create_all, so schema changes never silently bypass migrations.


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
templates = Jinja2Templates(directory="templates")


@app.get("/api/version")
def get_version():
    return {"version": GIT_SHA}


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


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """Never let the browser (or iOS's aggressive standalone-PWA cache) serve
    a stale copy of the app - these are single-user local tools, not public
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
app.include_router(scenarios.router)
app.include_router(monthly.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    from .config import HOST, PORT

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
