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

The first Telegram slice is now implemented: a secret-protected webhook, Telegram identity mapping, update-idempotency records, `/start` onboarding, `/help`, `/delete` with explicit `DELETE` confirmation, `/cancel`, and weight capture with historical measurement storage. Telegram processing is private-chat only. Legacy REST routes are temporarily prevented from selecting Telegram-owned profiles, but they still need proper authenticated multi-user ownership before public exposure.

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

Store secrets in the local environment only:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
DATABASE_URL=postgresql+asyncpg://postgres:fitkit@localhost:5432/fitkit
```

Never commit the bot token, webhook secret, API keys, or health data. The Telegram numeric `user_id` is the stable external identity used to link a Telegram account to an internal FitKit user profile; usernames are only display metadata.

## Current API endpoints

| Method | Endpoint | Purpose | Current status |
|---|---|---|---|
| `GET` | `/health` | Liveness check | Implemented |
| `POST` | `/ingest/health` | Health Auto Export payload | Implemented; currently single-user |
| `GET` | `/health/summary` | HRV, sleep, and resting-HR summary | Implemented; currently single-user |
| `POST` | `/workouts` | Structured workout logging | Implemented; currently single-user |
| `GET` | `/workouts/{exercise}/history` | Exercise history | Implemented; currently single-user |
| `GET` | `/workouts/{workout_id}` | Workout lookup | Implemented; currently single-user |
| `GET` | `/recommend/{exercise}` | Rule-based recommendation | Implemented; currently single-user |
| `POST` | `/integrations/telegram/webhook` | Telegram updates, `/start`, `/help`, `/delete`, `/cancel`, and weight onboarding | Implemented; private chats only; requires webhook secret and bot-token configuration |

## Quickstart

Requires Python 3.12 and PostgreSQL. Docker is convenient for local development.

```bash
pip install -e ".[dev]"

# Start PostgreSQL if it is not already running
docker run -d --name fitkit-postgres \
  -e POSTGRES_PASSWORD=fitkit \
  -p 5432:5432 postgres:16

python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
pytest tests/ -v
```

Configure `DATABASE_URL` in `.env` before starting the API. The application creates the current tables and seeds the exercise taxonomy at startup.

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
