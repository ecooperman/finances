"""Who may use this app: its administrators, and nobody else.

This is the household budget, so it is the most sensitive of the private apps. It has no accounts of its own; it
used to rely wholly on Cloudflare Access in front of it. Now it signs in through the shared front door (the
dashboard), and shared_python.owner_gate wraps the whole app, so every page, API route and file refuses anyone but
an administrator. Nothing is public and nothing else calls this app (it calls trips and lists, on this machine, with
their service tokens), so there is no exception of any kind."""
from shared_python import owner_gate

from . import config


def install(app) -> None:
    owner_gate.install(
        app,
        admin_emails=lambda: config.ADMIN_EMAILS,
        dev_user_email=config.DEV_USER_EMAIL,
    )
