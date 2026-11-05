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

# The trip-planning app's base URL, for the trip cost forecast (see
# app/services/trips.py). Same value local and in production: both talk to
# the trip-planning process directly on 127.0.0.1:8060, which sidesteps
# Cloudflare Access entirely. Only override if trip-planning moves.
TRIPS_API_BASE = os.environ.get("TRIPS_API_BASE", "http://127.0.0.1:8060")

# Trip-planning has accounts now, so these direct calls (no signed-in person on
# a server-to-server request) prove who they are with a shared secret, sent as
# X-Service-Token. Same value as trip-planning's TRIPS_SERVICE_TOKEN - set it
# once in /etc/personal-apps/shared.env (see DEPLOYMENT.md); unset, the header
# is simply not sent and trip-planning refuses the call.
TRIPS_SERVICE_TOKEN = os.environ.get("TRIPS_SERVICE_TOKEN")
