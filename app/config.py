import os

HOST = "127.0.0.1"
PORT = 8080

# "local" (default, for `uvicorn app.main:app --reload` on a dev machine) or
# "production" (set once, droplet-wide, via systemd's DefaultEnvironment -
# see DEPLOYMENT.md - so every app inherits it with no per-service config).
# Drives which shared-assets host the app's templates point at, so
# switching between local iteration and the real deploy never means
# hand-editing a URL and remembering to revert it.
ENV = os.environ.get("APP_ENV", "local")
SHARED_ASSETS_BASE = "https://static.evancooperman.com" if ENV == "production" else "http://127.0.0.1:8070"

# Where this app lives, for the links in the emails that tell people they have been let in.
PUBLIC_URL = "https://finances.evancooperman.com" if ENV == "production" else f"http://{HOST}:{PORT}"

# Who is signed in (shared_python): only people with an account get in, each into their own completely private
# finances (see app/access.py). ADMIN_EMAILS (comma-separated) comes from the shared secrets file on the droplet: they
# always have an account (made on first sign-in) and are the only ones who can let other people in, or use what reads
# the administrator's own trips and lists below. Locally the dev user is one, and is who every request is treated as.
DEV_USER_EMAIL = os.environ.get("DEV_USER_EMAIL", "dev@localhost.test").strip().lower()
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
if ENV != "production":
    ADMIN_EMAILS.add(DEV_USER_EMAIL)

# The trip-planning app's base URL, for the trip cost forecast (see
# app/services/trips.py). ADMINISTRATORS ONLY: the service token below reads the administrator's trips, so it is never
# used for anyone else (app/integrations.py). Same value local and in production: both talk to
# the trip-planning process directly on 127.0.0.1:8060, which sidesteps
# Cloudflare Access entirely. Only override if trip-planning moves.
TRIPS_API_BASE = os.environ.get("TRIPS_API_BASE", "http://127.0.0.1:8060")

# Trip-planning has accounts now, so these direct calls (no signed-in person on
# a server-to-server request) prove who they are with a shared secret, sent as
# X-Service-Token. Same value as trip-planning's TRIPS_SERVICE_TOKEN - set it
# once in /etc/personal-apps/shared.env (see DEPLOYMENT.md); unset, the header
# is simply not sent and trip-planning refuses the call.
TRIPS_SERVICE_TOKEN = os.environ.get("TRIPS_SERVICE_TOKEN")

# The lists app's base URL, for linked lists (see app/services/linked_lists.py; administrators only, like trips): a list that tracks
# costs can be linked into the budget as one lump sum, read live. Like trip-planning, called directly
# on 127.0.0.1 with a shared secret sent as X-Service-Token - the same value as lists'
# LISTS_SERVICE_TOKEN, set once in /etc/personal-apps/shared.env (see DEPLOYMENT.md). Unset, the header
# is not sent and lists refuses the call (linked lists then show as "not found in Lists").
LISTS_API_BASE = os.environ.get("LISTS_API_BASE", "http://127.0.0.1:8030")
LISTS_SERVICE_TOKEN = os.environ.get("LISTS_SERVICE_TOKEN")
