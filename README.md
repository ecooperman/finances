# Finances

Household finance tracker for Evan + Rach. Two ways of looking at money,
kept distinct:

- **Cash flow** - what actually leaves the account in a given month
  (recurring items that land + one-off transactions). The Overview's
  "This month" total.
- **Provisioning** - what a well-run month costs: lumpy recurring items
  smoothed to /month, plus **sinking funds** - money set aside monthly for
  costs you know are coming but can't schedule (vet visits, car repairs,
  gifts). The "Provisioned" figure.

Set up the knowns (recurring income/expenses), define funds for the fuzzy
stuff, log the one-off transactions that move the needle, tag each with a
person and category, and a **scenario** playground layers hypothetical
changes (add a car payment, halve the Uber spend, add a fund) over the
real budget without touching stored data.

Pulling real transactions from bank + credit-card accounts is a planned
follow-up - see [`SYNC.md`](SYNC.md).

## Pages

| Page | What it does |
|---|---|
| `/` (Overview) | Month stepper + person/category/scenario filters; a **payment calendar** (a one-month grid built from the same filtered data); money-in / money-out lists with a cash-flow net, a **Provisioned** figure (recurring smoothed + funds + trips), and a funds/trips status line. Read-only rollup + a unified "+ Add". |
| `/budget.html` | The one place to add and manage every money event. Segmented view (All / Recurring / One-time) over person/category/status/month filters; always-visible **Funds** and **Trips** sections; accordion cards for edit. Footer shows the provisioning baseline. |
| `/scenarios.html` | Create scenarios and their add / remove / scale-or-override adjustments - targeting recurring items **or** funds. "Open in Overview" applies one. |
| `/settings.html` | Manage the People and Category reference lists. |

**Adding an entry**: one "+ Add" form (Overview + Budget) with a
**One-time / Recurring / Fund** toggle - each saves to its own table
(`Transaction` / `RecurringItem` / `SinkingFund`); only the entry point is
merged. A one-time transaction can be **tagged to a fund** ("Draw from
fund"), which still counts as cash flow but also draws the fund's balance
down.

**Reference ID**: recurring items have an optional free-text
`reference_id` - a provider's key for a "pay in N months" plan (Affirm
loan id, Klarna order reference, PayPal ...). It's **unique across
recurring items**; adding or renaming one onto a value already in use is
rejected with a 409, so an accidental re-entry of the same plan gets
caught. Unset references never collide.

**Sinking funds**: defined by an annualized amount (entered however you
think about it - "$1,200/yr", "$85 every 7 weeks", "2× per year"). Each
contributes `annual / 12` to the provisioning figure every month and
carries a running **balance** = (accrued since its start month) − (tagged
transactions), which rolls over across years (overspend goes negative).
One-off transactions are *not* counted in the provisioning figure - an
unprovisioned surprise belongs in cash flow.

**Trips**: read **live** from the trip-planning app
(`TRIPS_API_BASE`, default `http://127.0.0.1:8060`, cached 30s) - its
`GET /api/trips/cost-summary` sums non-archived activity costs + booked
stay costs per trip. Each upcoming trip's cost is spread evenly across the
months from now through the trip's month (provisioning only, never cash
flow). **"Mark fully paid"** writes one `"<trip> (trip)"` transaction for
the total into cash flow and drops the trip from the forecast; a per-trip
**override** covers flights / anything not in trip-planning; **exclude**
hides one without settling. `TripSettlement.trip_id` is a bare int keyed
to trip-planning's DB - if that DB is wiped, settlements would point at
the wrong trips.

## API

Plain JSON REST under `/api` (`/docs` for Swagger):

- `/api/people`, `/api/categories` (+ `POST /api/categories/reorder`) - CRUD
- `/api/recurring` - CRUD (filters: `person_id`, `category_id`, `active`);
  `GET /api/recurring/summary` for the smoothed baseline
- `/api/transactions` - CRUD (filters: `month` or `date_from`/`date_to`,
  `person_id`, `category_id`); `POST /{id}/convert-to-recurring`
- `/api/recurring/{id}/convert-to-transaction`
- `/api/funds` - CRUD; each row carries computed `monthly_contribution_cents`,
  `balance_cents`, `spent_ytd_cents`; `GET /api/funds/summary` for the
  fleet roll-up. Balance math lives in `app/services/funds.py`.
- `/api/scenarios` - CRUD; `POST /api/scenarios/{id}/adjustments`;
  `PATCH`/`DELETE /api/adjustments/{id}`. Adjustments target
  `target_recurring_id` **or** `target_fund_id`; a fund `add` uses
  `add_kind: "fund"`.
- `/api/trips` - the trip forecast (`{upcoming, no_date, excluded}`);
  `GET /api/trips/summary`; `PATCH /api/trips/{trip_id}` (exclude /
  override); `POST /api/trips/{trip_id}/settle` and `/unsettle`. Costs come
  from trip-planning; only settlement state is stored here.
- `GET /api/monthly?month=YYYY-MM&person_id=&joint=&category_ids=&scenario_id=`
  - the aggregation the Overview page renders (`app/services/monthly.py`).
  `totals` = cash flow; `normalized` = provisioning (recurring smoothed +
  funds, one-offs excluded).

Money crosses the API as integer **cents** (`amount_cents`) in both
directions; the frontend converts at the input/display edge only.

## Tests

The aggregation, fund math, and trip forecasting are covered by
`tests/test_monthly.py`, `tests/test_funds.py`, and `tests/test_trips.py`
(the last monkeypatches the trip-planning call):

```bash
cd finances && source venv/bin/activate && pytest
```

## Depends on shared-assets

The nav bar uses four icons (`repeat`, `wallet`, `sliders`, `settings`)
added to `shared-assets/static/icons.js` - deploy shared-assets too, or the
nav icons render blank in production.

## Run it

```bash
cd finances
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.main
```

Then open http://127.0.0.1:8080 (host/port are set in `app/config.py`).

The SQLite database (`finances.db`) is not created by the app itself -
`alembic upgrade head` creates it. This only needs to be run once for a
fresh install; see below for how schema changes are handled from here on.

## Schema changes (Alembic)

Schema is owned by migrations under `migrations/versions/`, not by wiping
`finances.db`. To change the schema:

```bash
# 1. Edit app/models.py as usual
# 2. Generate a migration from the diff
alembic revision --autogenerate -m "short description"
# 3. Look over the generated file in migrations/versions/ - autogenerate
#    is good but not infallible (e.g. it won't detect a plain column rename
#    on its own)
# 4. Apply it
alembic upgrade head
```

This preserves existing data. Useful commands: `alembic current` (what
revision the db is at), `alembic check` (does the db match `models.py`
right now), `alembic downgrade -1` (undo the last migration).

SQLite can't `ALTER TABLE` to add a constraint directly, so
`migrations/env.py` has `render_as_batch=True` set, which makes autogenerate
wrap those changes in `op.batch_alter_table(...)` (SQLite rebuilds the table
under the hood). If autogenerate produces a `batch_op.create_foreign_key(None,
...)` / `drop_constraint(None, ...)` call, give it an explicit name in both
`upgrade()` and `downgrade()` - SQLite's batch mode needs a name to
reference, and will fail with `ValueError: Constraint must have a name`
otherwise.

## Upgrading to Postgres later

Everything goes through SQLAlchemy + Alembic, so moving off SQLite is mostly
a matter of swapping `DATABASE_URL` in `app/database.py` (and
`sqlalchemy.url` in `alembic.ini`) for a Postgres connection string,
installing a driver (`psycopg`), and running `alembic upgrade head` against
the new database - no application code depends on SQLite specifics.

## Deploying

Runs as a systemd service on the Digital Ocean droplet, reached through a
Cloudflare Tunnel (no inbound ports opened on the droplet) and gated by
Cloudflare Access - see `deploy/finances.service`.

One-time setup on the droplet:

```bash
sudo mkdir -p /opt/apps/finances && sudo chown deploy:deploy /opt/apps/finances
# as the deploy user:
git clone <this repo's SSH URL> /opt/apps/finances
cd /opt/apps/finances
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
sudo cp deploy/finances.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now finances
```

Then add an ingress entry for `127.0.0.1:8080` to `/etc/cloudflared/config.yml`,
route DNS for its hostname (`cloudflared tunnel route dns <tunnel-name>
<hostname>`), and add a Cloudflare Access policy for that hostname.

Ongoing deploys are automatic: `.github/workflows/deploy.yml` runs on every
push to `main` - it SSHes in, pulls, reinstalls dependencies, runs `alembic
upgrade head`, and restarts the service. Needs these repo secrets set once
(Settings -> Secrets and variables -> Actions): `DO_HOST`, `DO_USER` (the
`deploy` user), `DO_SSH_KEY` (that user's private key).

## Notes

- **Seed data**: the baseline migration seeds two people (`Evan`, `Rach`)
  and a starter set of categories - all editable on the Settings page.
- **Payment calendar** (Overview): a month grid rendered client-side from
  the `/api/monthly` response, so it honours the person/category/scenario
  filters and the scenario tinting for free. Recurring items with no
  `day_of_month` (and weekly/biweekly, and scenario-added lines) go in a
  "No set day" line under the grid. Rendered client-side by
  `renderCalendar()` in `static/app.js`. **Click a day** to open a detail
  modal (`openDayModal()`): every item that lands that day with its
  amount, cadence, category, person, schedule, start/end, reference ID,
  account and notes, plus a net total labelled **Net in** (a payday) or
  **Net out** with the in/out split and the month's running total through
  that day.
- **Opening balance / rollover** (Overview, above the calendar): each
  month opens with the previous month's **closing balance** - its opening
  plus its dated net cash flow, the figure the calendar's running balance
  ends on - so a big month (three paychecks) carries into the next instead
  of every month starting from $0. The calendar's `Σ` is now a running
  *balance* that starts at the opening. **Set actual** overrides the
  opening with your real balance (any sign, optional note) when the logged
  items don't add up; later months then roll forward from it, and **Back to
  rollover** removes the override. Rules: items with no set day aren't in
  it (same as the calendar's `Σ`); it's household-wide, so it's hidden when
  a person/category filter is on; scenarios don't change it. The **Until
  next paycheck** card uses it too: its headline is the balance you'll have
  *just before* payday (or how short you'll be) = balance now (opening +
  everything dated before today, today's income and logged daily spending
  included) + other income landing before payday - what's left to pay; it
  also shows the balance after the paycheck and payday bills. The chain
  starts at the `rollover_start_month` app setting (the migration sets it
  to the deploy month; earlier months open at $0 and don't roll) or the
  earliest override. `GET /api/monthly` returns `opening`;
  `PUT/DELETE /api/opening-balance/{month}`; `app/services/balance.py`.
- **Daily-spread items** (Ubers, food, anything you pay for most days): tick
  **"Spend this every day"** on a *monthly money-out* recurring item. The
  amount stays the monthly budget (totals, Provisioned and scenarios are
  unchanged) but is placed on the calendar as a **daily allowance** - the
  month split across its real days, cents exact. All the daily items fold
  into one `Daily $X` chip per calendar day, and they count on every day in
  the running total and the "Until next paycheck" card (which collapses
  them to one line per item; today counts only what's left of today's
  allowance). Click a day to **log what you actually spent**: each cost is
  its own entry (amount + optional note), so two Ubers in a day are two
  entries and the day totals them. A day with logged costs counts at the
  logged total; a day with none assumes the allowance (shown muted on past
  days), so the numbers fall back to the budget if you stop logging. The
  Overview's **Today's spending** card shows each item's allowance vs.
  spent today, what's left this month and per remaining day, and the
  over/under on logged days, with a quick-add row. API: `daily_spend` table,
  `POST/PATCH/DELETE /api/daily-spend`, `GET /api/daily-budget?on=`
  (`app/services/daily.py`). Daily items can't be carried over (nothing to
  carry - they're spent day by day), and a scenario rescales the plan but
  keeps real logged costs.
- **Carrying over unpaid items**: in the day pop-up, a money-out recurring
  item has **"Couldn't pay this - carry to <next month>"**. It's then
  dropped from that month's cash flow / running total (shown struck
  through, tagged "carried to Nov") and appears on the **1st of the next
  month** as a counted "↪ carried over from Oct" line. If that month you
  can't pay it either, the carried line has the same button and keeps
  rolling; a carried line you don't re-defer counts as paid in its month.
  **Undo** on the deferred row puts it back (and removes any later
  carries). A note under the calendar totals what came in and what went
  out. Whole-item-month granularity (a biweekly item with 3 paydays defers
  all 3), money-out items only (recurring, or a one-off transaction dated in
  that month), cash flow only (the Provisioned
  figure ignores it), and the "Until next paycheck" card honours it.
  Stored in `payment_deferrals` (`app/services/deferrals.py`,
  `POST /api/deferrals` with `recurring_item_id`+`month`, `transaction_id`,
  or `origin_id`; `DELETE /api/deferrals/{id}`).
- **Running total** (calendar): each day with entries shows its net plus
  a `Σ` month-to-date net (starts at $0 on the 1st, adds every dated
  payday and payment in order). Items with no set day can't be placed, so
  they're left out and listed under the grid. It's net activity, not a
  bank balance - there's no starting balance yet.
- **Date-grouped lists**: the money-in / money-out lists under the calendar
  group items by pay day, with a slim weekday/day-number gutter so the
  items keep their width (weekly items group under "↻", undated under "—").
- **Until next paycheck** (Overview, top card): `GET /api/until-paycheck`
  (`app/services/paycheck.py`) walks the real dated payments - recurring
  items placed by `schedule.py`, plus one-off transactions - from today to
  the next dated income (optionally one person's), at face amounts. Shows
  what's left to pay before it, what's also due on payday itself, and lists
  recurring money-out items it *can't* place (monthly with no day, weekly
  with no weekday) rather than silently under-counting. A paycheck landing
  today counts as already received.
- **Recurring frequencies**: `weekly`, `biweekly`, `monthly`, `quarterly`,
  `semiannual`, `annual`.
  - *quarterly / semi-annual / annual* need an `anchor_month`; they hit the
    cash-flow total only in their due month(s), but are spread evenly
    across the year in the "Provisioned" figures.
  - *weekly / biweekly* need no month anchor. If you set a **day of
    week**, the item is dated: the payment calendar draws one entry per
    real pay day at the **real per-payment amount**, and the **cash-flow**
    total counts every real pay day (a $6,000 biweekly paycheck is
    $18,000 in a 3-paycheck month, $12,000 in a 2-paycheck one). The
    **Provisioned** figure stays smoothed (`face × 52/12` or `× 26/12`)
    so it doesn't swing month to month. An item with *no* weekday set can't
    be placed, so it uses the smoothed amount in both. Biweekly also takes
    an optional **anchor date** to fix the every-14-days phase (no anchor
    → every other matching weekday
    from the first one in the month). `app/services/schedule.py` is the
    single source of truth for which days an item pays on.
  - See `FREQUENCY_PER_MONTH` / `FREQUENCY_INTERVAL_MONTHS` in
    `app/models.py` and `_recurring_amount` in `app/services/monthly.py`.
- **Funds** always contribute their flat `annual / 12` to provisioning,
  every month, regardless of the selected month. Deleting a fund nulls the
  `fund_id` on any transactions tagged to it (they stay).
- **Trips** need the trip-planning app reachable at `TRIPS_API_BASE`
  (a local `127.0.0.1` call in both dev and prod - it sidesteps Cloudflare
  Access). If it's down, the Trips section shows an unavailable notice and
  the rest of the app is unaffected. A trip with no `start_date` in
  trip-planning is listed but left out of the monthly math.
- **Scenarios never mutate stored rows** - `app/services/monthly.py`
  applies adjustments to in-memory copies per request. Recurring/one-off
  adjustments move `totals` (cash flow); fund adjustments move `normalized`
  (provisioning) - see `scenario.delta` vs `scenario.normalized_delta`.
- **`person_id` NULL = joint / whole household** (shown as a "Joint"
  badge), not "unknown".
