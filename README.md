# Finances

Household finance tracker for Evan + spouse: set up the **knowns** (monthly
and non-monthly recurring income/expenses - salaries, mortgage, HOA,
insurance, ...), log **ad-hoc transactions** that move the needle (big
one-offs, not every coffee), tag each line with a person and a category,
and see **money in minus money out** for any month. A **scenario**
playground layers hypothetical changes (add a car payment, halve the Uber
spend, drop a line) over the real budget without touching stored data.

Pulling real transactions from bank + credit-card accounts is a planned
follow-up - see [`SYNC.md`](SYNC.md).

## Pages

| Page | What it does |
|---|---|
| `/` (Overview) | Month stepper + person/category/scenario filters; money-in and money-out lists with a net at the bottom, plus a smoothed monthly-average net. Read-only rollup + a unified "+ Add". |
| `/budget.html` | The one place to add and manage every money event. Segmented view (All / Recurring / One-time) over person/category/status/month filters; accordion cards for edit. Footer shows the known monthly baseline. |
| `/scenarios.html` | Create scenarios and their add / remove / scale-or-override adjustments. "Open in Overview" applies one. |
| `/settings.html` | Manage the People and Category reference lists. |

**Adding an entry**: one "+ Add" form (on Overview and Budget) with a
**Repeats** toggle - off saves a dated one-time `Transaction`, on reveals
the schedule fields and saves a `RecurringItem`. The two are still
separate tables/endpoints; only the entry point is merged.

## API

Plain JSON REST under `/api` (`/docs` for Swagger):

- `/api/people`, `/api/categories` (+ `POST /api/categories/reorder`) - CRUD
- `/api/recurring` - CRUD (filters: `person_id`, `category_id`, `active`);
  `GET /api/recurring/summary` for the smoothed baseline
- `/api/transactions` - CRUD (filters: `month` or `date_from`/`date_to`,
  `person_id`, `category_id`)
- `/api/scenarios` - CRUD; `POST /api/scenarios/{id}/adjustments`;
  `PATCH`/`DELETE /api/adjustments/{id}`
- `GET /api/monthly?month=YYYY-MM&person_id=&joint=&category_ids=&scenario_id=`
  - the aggregation the Overview page renders (see
  `app/services/monthly.py`)

Money crosses the API as integer **cents** (`amount_cents`) in both
directions; the frontend converts at the input/display edge only.

## Tests

The monthly aggregation is covered by `tests/test_monthly.py`:

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

- **Seed data**: the baseline migration seeds two people (`Evan`, `Spouse`
  - rename `Spouse` on the Settings page) and a starter set of categories.
- **Non-monthly recurring items** land only in their due month(s) for the
  true cash-flow total, but are spread evenly across the year in the
  "smoothed monthly average" / "known monthly baseline" figures.
- **Scenarios never mutate stored rows** - `app/services/monthly.py`
  applies adjustments to in-memory copies per request.
- **`person_id` NULL = joint / whole household** (shown as a "Joint"
  badge), not "unknown".
