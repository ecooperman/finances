# Bank + credit-card sync (planned, not built)

The goal: stop hand-entering the big transactions and pull them straight
from the bank + credit-card accounts, then triage them (assign a category
+ person, or dismiss the sub-$100 noise).

## Why SimpleFIN Bridge

Evaluated Plaid, Teller, and SimpleFIN Bridge for a two-person household:

| | Cost | Covers cards? | Build + upkeep |
|---|---|---|---|
| **SimpleFIN Bridge** | ~$15/yr | yes | one bearer token, one `GET`, read-only, ~1 refresh/day |
| Teller.io | free (dev tier, 100 conns) | yes | mTLS client certs to manage; smaller vendor |
| Plaid | free trial ≤10 items, then usage pricing | yes | OAuth app approval, Plaid Link JS widget, webhooks |

SimpleFIN is the one actually built for read-only personal tools (it's
what Actual Budget uses). The once-a-day refresh limit is a non-issue for
a tracker that deliberately ignores small transactions. Decision locked
with Evan on 2026-08-27.

## Protocol shape

1. One-time: user creates a SimpleFIN Bridge account, connects their
   institutions there, and gets a **setup token** (base64). Exchange it
   once (`POST` to the decoded claim URL) for a permanent **access URL**
   of the form `https://<user>:<pass>@bridge.simplefin.org/simplefin`.
   Store that access URL server-side only.
2. Ongoing: `GET {access_url}/accounts?start-date=<unix>&pending=1` returns
   `{ accounts: [ { id, name, org, balance, currency, transactions: [
   { id, posted, amount, description, pending } ] } ] }`. Amounts are
   signed decimal strings (negative = money out).

## Planned implementation

- **Config**: `SIMPLEFIN_ACCESS_URL` env var (never committed; set in the
  systemd unit or a droplet env file). Absent = sync UI hidden.
- **New model `Account`**: `institution`, `name`, `type` (`bank`/`card`),
  `simplefin_account_id` (unique), `last_synced_at`, `balance_cents`. One
  Alembic migration adds it; `Transaction` already carries `source`,
  `external_id`, `account_name`, `pending` for this.
- **`app/sync/simplefin.py`**: fetch since `min(last_synced_at) - 3 days`,
  then per transaction upsert on `(source="simplefin", external_id=txn.id)`
  (the existing unique constraint). Map signed amount ->
  `amount_cents` + `direction`; leave `category_id` / `person_id` NULL.
  Update each `Account.balance_cents` / `last_synced_at`.
- **Route**: `POST /api/sync/simplefin` (manual trigger) returning
  `{ imported, updated, accounts }`. A "Sync now" action in the nav.
- **Triage view**: a page (or a Monthly-view section) listing
  `source="simplefin"` transactions with no category - inline assign
  category + person, or "dismiss" (a `dismissed` flag, or just delete).
  Dismissed/kept state keeps the list short.
- **Later**: a daily `systemd` timer on the droplet calling the sync route
  (or the module directly) so it's hands-off.

## Not doing

- Real-time webhooks / balance alerts - out of scope for a monthly
  planning tool.
- Auto-categorization rules - revisit only if manual triage gets tedious.
- Payment initiation / moving money - never.
