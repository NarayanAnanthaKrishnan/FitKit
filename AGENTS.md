# FitKit — Telegram Fitness Coach

FitKit is a Telegram-first fitness coaching backend. The current repository contains a tested deterministic rule engine and a single-user FastAPI/PostgreSQL API. The next product phase adds a secure Telegram adapter, multi-user ownership, progress history, and a private insights dashboard.

## Core design principles

1. **The rule engine is the product.** Recommendations come from deterministic code in `engine/`. A language model may parse or phrase messages, but it must never silently override numeric rules.
2. **One graceful data path.** Health and activity data are optional. Missing data must degrade to an explicit insufficient-data result; do not create separate watch-connected and watch-disconnected business logic.
3. **Defensive writes.** Never guess a weight, exercise, reps, load, RPE, date, or goal. Ambiguous mutations require clarification or confirmation.
4. **User ownership everywhere.** Every user-owned query and write must be scoped by authenticated internal `user_id`. Never use `select(UserProfile).limit(1)` in new code.
5. **Telegram is an adapter, not the domain.** Telegram handlers translate updates into validated domain-service calls. Domain services must not depend on Telegram payloads.
6. **Privacy by default.** Bot tokens, webhook secrets, health data, conversation contents, and dashboard tokens must not be logged, committed, or exposed to other users.
7. **Test the engine and boundaries.** Keep `engine/` free of FastAPI and SQLAlchemy imports. Add unit tests for domain rules and integration tests for Telegram security, identity, idempotency, and data isolation.

## Repository structure

```text
api/
├── main.py                  FastAPI application and lifespan
├── dependencies/            Authentication and request dependencies
├── models/db.py             SQLAlchemy persistence models
├── routers/                 REST API routes
├── services/                Shared domain/query services
└── schemas.py               Pydantic request/response models
engine/                      Framework-independent fitness rules
docs/
├── data_schema.md           Current schema and planned Telegram additions
└── exercise_taxonomy.csv    Canonical exercise vocabulary
scripts/fetch_wger.py        Optional exercise taxonomy generator
tests/
├── test_engine/             Rule-engine unit tests
└── test_api/                API integration tests
```

The former empty ML parser/voice placeholders were removed. Do not reintroduce model-specific directories until an actual model implementation is approved.

## Current functionality

The engine provides:

- Epley estimated 1RM
- Primary-set progressive overload
- ACWR and volume calculations
- HRV/sleep recovery gates
- Recommendation orchestration

The API provides the current structured workout routes, health summary, Health Auto Export ingestion, recommendation route, and the initial Telegram webhook slice. Telegram identity, update idempotency, `/start`, `/help`, `/delete` with explicit confirmation, `/cancel`, and weight measurement capture exist; Telegram processing is private-chat only. The legacy REST routes remain effectively single-user and the full multi-user ownership layer, goals, conversation storage, dashboard, and HealthKit companion are still planned.

## Telegram architecture

The planned flow is:

```text
Telegram Bot API
    -> POST /integrations/telegram/webhook
    -> verify X-Telegram-Bot-Api-Secret-Token
    -> deduplicate Telegram update_id
    -> resolve Telegram user_id to internal user_id
    -> conversation/agent orchestration
    -> domain services
    -> PostgreSQL and engine
    -> Telegram response or expiring dashboard link
```

Bot credentials belong only in environment variables such as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET`. The Telegram numeric user ID is the stable external identity; username is not a primary key.

Telegram cannot directly access Apple Health or HealthKit. The short-term prototype bridge is the third-party Health Auto Export service and requires explicit user configuration. The long-term, Apple-supported solution is a native iOS companion app that requests HealthKit permissions and synchronizes approved data to the backend.

## Domain-service boundaries

Implement shared services before adding complex handlers. Typical tools include:

```text
record_weight()
log_workout()
get_activity_summary()
get_recovery_summary()
get_progress_summary()
get_recommendation()
generate_dashboard_link()
delete_user_data()
```

REST routes and Telegram handlers should call the same services. Do not make the Telegram adapter call the local REST API over HTTP merely to reuse logic.

Mutating operations should be auditable. Store the interpreted action, validation result, and outcome in an agent-action record. Destructive operations always need explicit confirmation.

## Data and schema rules

- Preserve weight measurements as history; do not overwrite the only record in `UserProfile`.
- Keep health metrics linked to the correct internal user and source.
- Use idempotency keys for Telegram updates and health-ingest batches.
- Dashboard links must be opaque, short-lived, user-scoped, and revocable.
- Do not put raw health data, bot tokens, or internal identifiers in URLs.
- Introduce a migration tool before production schema evolution; `create_all` is currently only the local bootstrap and migrations are not yet installed.
- Keep exercise names in the canonical taxonomy. Parsers normalize into taxonomy names; they do not create arbitrary exercise records.
- Missing RPE remains missing; do not default it for recommendation decisions.

## Local operations

- Start PostgreSQL before launching the API.
- The current Health Auto Export endpoint is a prototype bridge; verify one real payload's metric names and skipped count before relying on it.
- Keep local Uvicorn output out of source control. The repository may contain locked transient log files from a running/local execution environment; remove them when no process holds them.

## Testing expectations

Run the relevant tests after changes:

```bash
pytest tests/test_engine -v
pytest tests/test_api -v
pytest tests/ -v
```

New Telegram work must include tests for:

- Invalid and valid webhook secret handling
- Unknown or malformed updates
- Duplicate `update_id` handling
- Correct Telegram-user-to-internal-user mapping
- User data isolation
- Destructive command confirmation and cancellation
- Telegram API failure and retry behavior
- No duplicate workout or weight writes

## Roadmap

1. Replace legacy implicit single-user behavior with explicit authenticated ownership; Telegram profiles are currently excluded from legacy lookups as a temporary boundary.
2. Harden Telegram identity concurrency, outbound delivery, and webhook retry semantics.
3. Add goals, conversations, and agent-action audit records; initial weight measurements already exist.
4. Build a minimal Telegram vertical slice: `/start`, weight logging, `/today`, `/progress`.
5. Add workout parsing and validated logging using the existing taxonomy and engine.
6. Build a private dashboard and secure Telegram links.
7. Make Health Auto Export user-aware and validate real payloads.
8. Build a native iOS HealthKit companion when the Telegram MVP is proven.

Do not start with reminders, fine-tuning, voice, or broad frontend work before the core user-owned Telegram flow is reliable.
