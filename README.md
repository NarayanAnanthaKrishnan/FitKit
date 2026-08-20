# FitKit — Telegram Fitness Coach

FitKit is a fitness-coaching backend designed to support a conversational Telegram agent. Users will be able to log workouts, record progress, ask for health and training summaries, receive deterministic recommendations, and open a private insights dashboard.

The existing rule engine remains the product's decision-making core. A future language model may interpret messy messages or phrase responses, but it must not replace the validated fitness rules.

## Product direction

```text
Telegram chat
    -> Telegram Bot API
    -> FastAPI webhook and conversation layer
    -> validated domain services
    -> PostgreSQL + deterministic rule engine
    -> Telegram replies and private dashboard links
```

Telegram is the primary interaction channel. A web dashboard is for charts and deeper insights, not for replacing the chat experience.

## Current implementation

The repository currently contains the backend foundation:

- `engine/` — framework-independent fitness calculations and recommendations
- `api/` — FastAPI REST API, SQLAlchemy models, health ingestion, and database services
- `tests/` — engine unit tests and API integration tests
- `docs/exercise_taxonomy.csv` — canonical exercise vocabulary
- `scripts/fetch_wger.py` — optional taxonomy generation helper

Implemented capabilities include:

- Epley estimated 1RM
- Progressive overload decisions using the primary set
- Acute:chronic workload ratio calculations
- HRV and sleep recovery gates
- Daily training-volume aggregation
- Workout session CRUD
- Health Auto Export ingestion for selected Apple Watch metrics
- Health summaries and exercise recommendations
- Idempotent health-metric insertion

The first Telegram slice is now implemented: a secret-protected webhook, Telegram identity mapping, update-idempotency records, `/start` onboarding, `/help`, `/delete` with explicit `DELETE` confirmation, `/cancel`, and weight capture with historical measurement storage. Telegram processing is private-chat only. The structured REST routes now require the application API key plus `X-Telegram-User-Id`, and resolve that linked Telegram identity to an internal user before reading or writing data. This is an internal bridge, not public user authentication; do not expose these routes publicly until a real authenticated user context replaces it.

## Telegram and health-data boundaries

A Telegram bot cannot directly read Apple Health or Apple Watch data and cannot display the iOS HealthKit permission prompt. Telegram provides the conversation interface, while health data must arrive through a separate authorized source.

### Initial bridge

The short-term prototype path keeps the existing third-party Health Auto Export flow. It requires user configuration and is not a Telegram permission mechanism or the long-term Apple integration:

```text
Apple Health / Watch
    -> Health Auto Export
    -> POST /ingest/health
    -> health_metrics
    -> Telegram summaries
```

### Long-term Apple integration

The production Apple path is a native iOS companion app using HealthKit:

```text
Apple Watch / iPhone
    -> HealthKit permissions in a native iOS app
    -> authenticated sync to FitKit
    -> Telegram agent and dashboard
```

The companion app will request only the health categories the user approves. Telegram can link to the setup flow, but it cannot grant HealthKit permissions by itself.

## Telegram bot setup

The bot will be created through Telegram's `@BotFather`. BotFather provides a secret bot token used by the backend to call the Telegram Bot API.

Store secrets in the local environment only. Start from the safe template:

```bash
cp .env.example .env
```

Then replace every placeholder in `.env` with local values. Never commit `.env`, the bot token, webhook secret, API keys, database credentials, or health data. If a credential is exposed, rotate it immediately; deleting the file is not enough.

The Telegram numeric `user_id` is the stable external identity used to link a Telegram account to an internal FitKit user profile; usernames are only display metadata.

## Current API endpoints

| Method | Endpoint | Purpose | Current status |
|---|---|---|---|
| `GET` | `/health` | Liveness check | Implemented |
| `POST` | `/ingest/health` | Health Auto Export payload | Implemented; API-key + linked Telegram identity required |
| `GET` | `/health/summary` | HRV, sleep, and resting-HR summary | Implemented; user-scoped through linked Telegram identity |
| `POST` | `/workouts` | Structured workout logging | Implemented; user-scoped through linked Telegram identity |
| `GET` | `/workouts/{exercise}/history` | Exercise history | Implemented; user-scoped through linked Telegram identity |
| `GET` | `/workouts/{workout_id}` | Workout lookup | Implemented; user-scoped through linked Telegram identity |
| `GET` | `/recommend/{exercise}` | Rule-based recommendation | Implemented; user-scoped through linked Telegram identity |
| `POST` | `/integrations/telegram/webhook` | Telegram updates, `/start`, `/help`, `/delete`, `/cancel`, and weight onboarding | Implemented; private chats only; requires webhook secret and bot-token configuration |

## Quickstart

Requires Python 3.12 and PostgreSQL. Docker is convenient for local development.

Configure `DATABASE_URL` in `.env` before starting the API. Apply the schema explicitly before startup:

```bash
cp .env.example .env
# Edit .env and replace every placeholder.
```

Create and activate the project virtual environment manually, then install the constrained dependencies:

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
# source .venv/bin/activate    # Linux/macOS

python -m pip install --upgrade pip
python -m pip install -c constraints.txt -e ".[dev]"
```

Start PostgreSQL and apply migrations with one command. It starts Docker Desktop if needed, ensures the `fitkit-postgres` container is running, creates the `fitkit` and `fitkit_test` databases, and migrates to head (idempotent — safe to re-run):

```bash
bash scripts/devdb.sh
```

Then run the backend directly from the active virtual environment. Structured REST requests must include both `X-API-Key` and `X-Telegram-User-Id` for an already-linked Telegram account; Telegram webhook calls use their separate webhook secret:

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is available at `http://localhost:8000`. Keep the backend terminal open and stop it with `Ctrl+C`.

Run tests from another terminal after activating `.venv` there as well:

```bash
python -m pytest tests/ -v
```

For an existing legacy database, make a backup and use the explicit validated bootstrap command:

```bash
python scripts/bootstrap_legacy_db.py --apply
```

This command creates only missing current-model tables, applies the known onboarding nullability compatibility changes, verifies required columns, and then records the Alembic baseline. It refuses to run when an Alembic version already exists. Do not use `alembic stamp head` directly unless the schema has been manually verified.

The application seeds the static exercise taxonomy at startup, but it no longer creates or alters database tables implicitly. Apply migrations explicitly before starting the backend. If `fitkit_test` already exists, the one-time `createdb` command can be skipped.

### Alembic and Mako files

Alembic is the versioned database-schema tool. Keep `alembic.ini`, `alembic/env.py`, the migration files under `alembic/versions/`, and `alembic/script.py.mako` in source control. The first three configure/run/apply migrations; `script.py.mako` is the template used when generating a future revision. Mako itself is only a Python dependency installed into `.venv` for Alembic's template rendering. Do not commit `.venv`, `__pycache__`, or generated Mako/package files.

## Repository layout

```text
api/
  dependencies/       Authentication helpers
  models/             SQLAlchemy models
  routers/            REST routes
  services/           Shared database queries
engine/               Deterministic fitness rule engine
docs/
  data_schema.md      Current schema and planned Telegram-era additions
  exercise_taxonomy.csv
scripts/
  fetch_wger.py       Exercise taxonomy helper
tests/                Engine and API tests
```

Generated logs, caches, environment files, and package metadata are local artifacts and are ignored by `.gitignore`. The existing `uvicorn_out.log` and `uvicorn_err.log` files are locked by the local execution environment and remain temporarily; they are not application source and should be removed when no process holds them.

For local operations, start PostgreSQL before the API and inspect the Uvicorn logs when available. Before relying on production health data, send one real Health Auto Export payload and verify the metric names and skipped-entry count.

## Roadmap

1. **Multi-user foundation** — replace legacy first-user lookups with explicit ownership and migrations
2. **Telegram vertical slice expansion** — profile, goals, inline confirmations, and robust outbound delivery
3. **Progress tracking** — broader weight history, goals, and weekly summaries
4. **Workout conversation** — validated natural-language parsing and workout logging
5. **Private dashboard** — expiring links and user-scoped charts
6. **Health connection** — user-aware Health Auto Export, then a native HealthKit companion
7. **Agent orchestration** — strict tools, confirmations, audit history, and evaluation
8. **Optional reminders** — opt-in check-ins and weekly reports

See `fitness-agent-implementation-plan.md` for the detailed plan and acceptance criteria. See `docs/data_schema.md` before changing persistence models.
