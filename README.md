# FitKit — Telegram Fitness Coach

FitKit is a fitness-coaching backend designed to support a conversational Telegram agent. Users will be able to log workouts, record progress, ask for health and training summaries, receive deterministic recommendations, and open a private insights dashboard.

The existing rule engine remains the product's decision-making core. A language model interprets messy free-text messages and phrases responses on Groq `openai/gpt-oss-120b`, but it never replaces validated fitness rules — every LLM candidate is Pydantic-validated and requires a Save/Cancel preview.

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
- User-scoped Apple Health ingestion through the first-party Apple Shortcuts bridge
- Optional legacy Health Auto Export ingestion during migration
- Health summaries and exercise recommendations
- Idempotent health-metric insertion
- Copy-ready Shortcut recipe in `docs/apple_shortcuts.md`
- Provider-neutral LLM gateway on Groq `openai/gpt-oss-120b` — bounded intent + structured extraction for free-text Telegram messages with confidence-gated previews
- Synthetic eval set in `tests/eval/cases.jsonl` + benchmark harness `scripts/eval_groq.py`

Telegram is now full-slice with optional LLM: secret-protected webhook, Telegram identity mapping, update-idempotency, `/start`, `/help`, `/delete` with `DELETE` confirmation, `/cancel`, weight capture with Save/Cancel preview, `/log` with preview + inline Edit, `/profile`, `/goals`, `/today`, `/progress`, `/health`, `/connect-health`, `/dashboard`, and `/recommend`. Free-text like `my weight is 82 kg` or `bench 3x8 at 80 kg rpe 8` is routed through the Groq gateway only when `LLM_ENABLED=1`; low-confidence or invalid output asks clarification, and every write still requires confirmation. Telegram processing is private-chat only. The structured REST routes require `X-API-Key` + `X-Telegram-User-Id` resolving a linked Telegram identity — internal bridge only, not public auth.

## Telegram and health-data boundaries

A Telegram bot cannot directly read Apple Health or Apple Watch data and cannot display the iOS HealthKit permission prompt. Telegram provides the conversation interface, while health data must arrive through a separate authorized source.

### Production bridge without a third-party exporter or FitKit iOS app

Apple Health cannot be read from a server, and Telegram cannot grant HealthKit permissions. The supported no-app path is the first-party Shortcuts bridge:

```text
Apple Health / Watch
    -> Apple Shortcuts personal automation
    -> POST /ingest/shortcut with a per-user pairing token
    -> health_metrics
    -> Telegram summaries and recommendations
```

Users run `/connect-health` in Telegram, copy their private endpoint and token into the Shortcut, and configure a daily personal automation. The complete recipe is in [`docs/apple_shortcuts.md`](docs/apple_shortcuts.md).

This is a daily best-effort sync, not an always-on stream. Apple may require the phone to be unlocked, and Health/Shortcuts availability varies by iOS version. The older third-party Health Auto Export route is disabled by default and can be enabled during rollout with `ALLOW_LEGACY_INGEST_AUTH=1`.

## Telegram bot setup

The bot will be created through Telegram's `@BotFather`. BotFather provides a secret bot token used by the backend to call the Telegram Bot API.

Store secrets in the local environment only. Start from the safe template:

```bash
cp .env.example .env
```

Then replace every placeholder in `.env` with local values. Minimum for the full stack:

| Variable | Required for | Notes |
|---|---|---|
| `DATABASE_URL` | always | `postgresql+asyncpg://postgres:fitkit@localhost:5432/fitkit` for local dev |
| `FITKIT_API_KEY` | REST bridge | internal key for `X-API-Key` |
| `TELEGRAM_BOT_TOKEN` | Telegram | from `@BotFather`, never commit |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram | long random string, sent as `secret_token` on webhook registration |
| `PUBLIC_BASE_URL` | health + dashboard links | e.g. `http://localhost:8000` locally, `https://fitkit.example.com` in staging |
| `GROQ_API_KEY` | LLM | Groq console key for `openai/gpt-oss-120b`; omit or set `LLM_ENABLED=0` to run without LLM |
| `GROQ_MODEL` | LLM | `openai/gpt-oss-120b` (default); override only for experiments |
| `LLM_ENABLED` | LLM | `1` to enable free-text gateway, `0` to disable (fallback to deterministic commands) |

Never commit `.env`, the bot token, webhook secret, `GROQ_API_KEY`, API keys, database credentials, or health data. If a credential is exposed, rotate it immediately; deleting the file is not enough.

The Telegram numeric `user_id` is the stable external identity used to link a Telegram account to an internal FitKit user profile; usernames are only display metadata.

> **LLM off by default:** If `GROQ_API_KEY` is missing or `LLM_ENABLED=0`, the gateway falls back to deterministic commands (`/start`, `/log`, bare weight like `80 kg`) and asks `Send /help` for unrecognized free text. No Groq call is made and no tests require a live key.

## Current API endpoints

| Method | Endpoint | Purpose | Current status |
|---|---|---|---|
| `GET` | `/health` | Liveness check | Implemented |
| `POST` | `/ingest/shortcut` | First-party Apple Shortcuts health payload | Implemented; per-user pairing token required |
| `POST` | `/ingest/health` | Legacy Health Auto Export payload | Implemented; disableable rollout compatibility path |
| `GET` | `/health/summary` | HRV, sleep, and resting-HR summary | Implemented; user-scoped through linked Telegram identity |
| `POST` | `/workouts` | Structured workout logging | Implemented; user-scoped through linked Telegram identity |
| `GET` | `/workouts/{exercise}/history` | Exercise history | Implemented; user-scoped through linked Telegram identity |
| `GET` | `/workouts/{workout_id}` | Workout lookup | Implemented; user-scoped through linked Telegram identity |
| `GET` | `/recommend/{exercise}` | Rule-based recommendation | Implemented; user-scoped through linked Telegram identity |
| `POST` | `/integrations/telegram/webhook` | Telegram updates, `/start`, `/help`, `/delete`, `/cancel`, and weight onboarding | Implemented; private chats only; requires webhook secret and bot-token configuration |

## Quickstart

Requires Python 3.12 and PostgreSQL. Docker is convenient for local development. Groq access is optional — see LLM rows in the table above.

### 1. Configure the environment

```bash
cp .env.example .env
# Edit .env and replace every placeholder.
# For Telegram + LLM locally:
#   TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET from @BotFather
#   PUBLIC_BASE_URL=http://localhost:8000 (or your tunnel host in staging)
#   GROQ_API_KEY from https://console.groq.com (leave unset + LLM_ENABLED=0 to run without LLM)
```

### 2. Create the virtual environment

Run these commands manually from the repository root:

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
# source .venv/bin/activate    # Linux/macOS

python -m pip install --upgrade pip
python -m pip install -c constraints.txt -e ".[dev]"
```

### 3. Start PostgreSQL and migrate

One idempotent command starts Docker Desktop if needed, ensures the `fitkit-postgres` container is running, creates the `fitkit` and `fitkit_test` databases, and migrates to head:

```bash
bash scripts/devdb.sh
```

Manual equivalent (Linux/macOS or if the script is unavailable):

```bash
docker run -d --name fitkit-postgres -e POSTGRES_PASSWORD=fitkit -p 5432:5432 postgres:16
until docker exec fitkit-postgres pg_isready -U postgres; do sleep 1; done
docker exec fitkit-postgres createdb -U postgres fitkit
docker exec fitkit-postgres createdb -U postgres fitkit_test
python -m alembic upgrade head
```

For a pre-existing local database that predates Alembic, back up first then:

```bash
python scripts/bootstrap_legacy_db.py --apply
```

### 4. Run the API

From the active virtual environment, with PostgreSQL running:

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

- The API is available at `http://localhost:8000`; liveness check is `GET /health`.
- Structured REST requests must include both `X-API-Key` and `X-Telegram-User-Id` for an already-linked Telegram account; Telegram webhook calls use the separate `X-Telegram-Bot-Api-Secret-Token` header.
- With `LLM_ENABLED=1` and a valid `GROQ_API_KEY`, free-text like `my weight is 82 kg` is interpreted via Groq `openai/gpt-oss-120b` into a preview; with `LLM_ENABLED=0` the same input falls back to `Send /help`.
- Keep the backend terminal open and stop it with `Ctrl+C`.

### 5. Run tests

From another terminal after activating `.venv` there as well:

```bash
# All tests (mocked LLM — no Groq key or network needed):
python -m pytest tests/ -v
# Or by suite:
python -m pytest tests/test_engine -v
python -m pytest tests/test_api -v
# Optional: real Groq benchmark (requires GROQ_API_KEY; synthetic data only):
python scripts/eval_groq.py --model openai/gpt-oss-120b
# Offline eval (no Groq key):
python scripts/eval_groq.py --mock
```

The application seeds the static exercise taxonomy at startup, but it no longer creates or alters database tables implicitly. Apply migrations explicitly before starting the backend. If `fitkit_test` already exists, the one-time `createdb` command can be skipped.

### 6. Expose Telegram locally (optional)

For Telegram, the bot needs a public HTTPS URL. Use Cloudflare Tunnel or ngrok:

```bash
# Example with Cloudflare Tunnel (install cloudflared first):
cloudflared tunnel --url http://localhost:8000
# or: ngrok http 8000
```

Then register the development bot webhook (replace `TUNNEL_HOST`):

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://TUNNEL_HOST/integrations/telegram/webhook","secret_token":"'"$TELEGRAM_WEBHOOK_SECRET"'","max_connections":40}'
# Verify:
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
curl http://localhost:8000/health
```

When the tunnel URL changes, re-register the webhook and verify `/health` before testing `/start` in Telegram. Keep webhook URLs that contain bot tokens out of logs.

### Alembic and Mako files

Alembic is the versioned database-schema tool. Keep `alembic.ini`, `alembic/env.py`, the migration files under `alembic/versions/`, and `alembic/script.py.mako` in source control. The first three configure/run/apply migrations; `script.py.mako` is the template used when generating a future revision. Mako itself is only a Python dependency installed into `.venv` for Alembic's template rendering. Do not commit `.venv`, `__pycache__`, or generated Mako/package files.

## Repository layout

```text
api/
  dependencies/       Authentication helpers
  llm/                Provider-neutral Groq gateway (gpt-oss-120b) + schemas
  models/             SQLAlchemy models
  routers/            REST routes
  services/           Shared domain/query services
engine/               Deterministic fitness rule engine
docs/
  apple_shortcuts.md  Copy-ready Shortcuts recipe
  data_schema.md      Current schema and planned personalization tables
  development.md      Local setup and Telegram/LLM testing
  exercise_taxonomy.csv
scripts/
  devdb.sh            Idempotent PostgreSQL + migration bootstrap
  eval_groq.py        Groq benchmark harness for tests/eval
  fetch_wger.py       Exercise taxonomy helper
tests/
  eval/cases.jsonl    Synthetic LLM eval set (versioned)
  test_engine/        Rule-engine unit tests
  test_api/           API integration tests (mocked LLM in normal CI)
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
7. **Agent orchestration** — strict tools, confirmations, audit history, and evaluation (Groq `openai/gpt-oss-20b` + `openai/gpt-oss-120b` pilot via provider-neutral gateway)
8. **Optional reminders** — opt-in check-ins and weekly reports
9. **Personalized coaching (post-LLM) — per-user food/water logging and tailored nudges, deterministic targets in `engine/`, Groq-phrased

See `fitness-agent-implementation-plan.md` for the detailed plan and acceptance criteria. See `docs/data_schema.md` before changing persistence models.
