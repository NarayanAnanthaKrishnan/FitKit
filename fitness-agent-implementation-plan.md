# FitKit — Telegram-First Implementation Plan

## Product definition

FitKit is a conversational fitness coach delivered primarily through Telegram. A user can log workouts and progress in chat, ask for health and training summaries, receive deterministic recommendations, and open a private web dashboard for charts and deeper insights.

The existing rule engine remains the decision-making core. Natural-language parsing is an interface convenience; it must produce validated structured inputs and must not invent missing values or override the engine.

## Current baseline

Already implemented:

- Framework-independent engine modules for 1RM, overload, ACWR, recovery, calories, volume, and recommendation orchestration
- PostgreSQL/SQLAlchemy models for profiles, workouts, exercise sets, health metrics, and exercise taxonomy
- FastAPI routes for structured workout logging, history, recommendations, health summaries, and Health Auto Export ingestion
- Idempotent health-metric insertion
- Engine unit tests and API integration tests
- Canonical exercise taxonomy in `docs/exercise_taxonomy.csv`

Implemented in the first Telegram slice:

- Secret-protected Telegram webhook
- Telegram identity linked to internal users
- Telegram update-idempotency records
- `/start`, `/help`, `/delete` with explicit `DELETE` confirmation, and `/cancel`
- Initial weight capture with historical measurement storage
- Private-chat-only handling for sensitive profile and deletion operations

Still not implemented:

- Multi-user ownership for the existing REST routes and migrations
- Goals and complete profile editing
- Conversation and agent-action persistence
- Natural-language workout orchestration
- Private dashboard and expiring links
- Native iOS HealthKit companion

The existing REST API still assumes one user in several places. It must not be exposed as a public multi-user product until that is fixed.

## Target architecture

```text
Telegram Bot API
    -> FastAPI Telegram webhook
    -> webhook authentication + update idempotency
    -> Telegram user identity resolution
    -> conversation and agent orchestration
    -> validated domain services
    -> PostgreSQL and deterministic engine
    -> Telegram response / private dashboard link

Apple Watch / iPhone health data
    -> Health Auto Export initially, native HealthKit app later
    -> authenticated, user-scoped ingestion
    -> health/activity summaries and recommendations
```

Telegram cannot directly read Apple Health or grant HealthKit permissions. A native iOS companion app is required for the long-term Apple integration. Telegram may link to that setup flow or host a dashboard in a Mini App, but a Mini App is not a substitute for HealthKit permissions.

## Configuration and external setup

Create the bot with Telegram's `@BotFather`. Keep the returned token only in backend environment configuration:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
DATABASE_URL=postgresql+asyncpg://postgres:fitkit@localhost:5432/fitkit
```

The Telegram numeric `user_id` is the stable external identity. Store it with the internal user mapping; do not use username as the primary identity. Configure webhooks only over HTTPS in a deployed environment and validate Telegram's secret-token header on every webhook request.

## Phase 0 — Baseline and cleanup

Status: complete.

- Retain the rule engine, API, tests, taxonomy, and WGER helper.
- Remove generated logs/caches/package metadata when not locked by the local environment.
- Remove unused empty ML parser/voice placeholders.
- Replace the old REST/frontend/model roadmap with this Telegram-first plan.

## Phase 1 — Multi-user foundation

Status: partially complete. Telegram identity and update-idempotency tables now exist, but the legacy REST routes still use implicit first-user lookup.

Goal: establish trustworthy identity and ownership across every route before exposing the product publicly.

Work:

- Add a stable account identity model or equivalent Telegram identity fields.
- Store unique `telegram_user_id`, chat ID, display metadata, and timestamps.
- Replace every implicit first-user lookup with explicit internal `user_id` resolution.
- Scope workouts, health metrics, summaries, recommendations, and future conversations by user.
- Introduce schema migrations instead of relying on `create_all` for future changes.
- Add user-isolation and account-linking tests.

Acceptance criteria:

- Two distinct Telegram identities resolve to two internal users.
- No user can read or modify another user's workouts or health metrics.
- Existing engine tests remain unchanged and passing.

## Phase 2 — Telegram vertical slice

Status: initial slice complete; expansion remains.

Goal: make the product usable through Telegram without an LLM dependency.

Work:

Completed:

- Add `POST /integrations/telegram/webhook`.
- Validate `X-Telegram-Bot-Api-Secret-Token`.
- Parse private-chat text messages.
- Store and mark processed `update_id` values to make retries safe.
- Add a minimal Telegram Bot API client for outbound text replies.
- Implement `/start`, `/help`, and initial weight onboarding.
- Create or link the internal user on `/start`.
- Store the first weight as both the current snapshot and a historical measurement.

Remaining:

- Parse callback queries and add inline confirmations.
- Implement `/profile`, `/today`, `/goals`, `/health`, and `/insights`.
- Move deletion into a shared domain service and extend its deletion registry as new user-owned tables are added.
- Improve concurrent identity creation and outbound retry handling.

Acceptance criteria:

- A real Telegram message reaches the backend and receives a reply.
- Invalid webhook requests are rejected.
- Retried updates do not duplicate actions or responses.
- Bot token and webhook secret never appear in logs or source control.

## Phase 3 — Progress and profile tracking

Goal: support trustworthy progress updates.

Work:

- Add `weight_measurements` history rather than overwriting profile weight.
- Add goals with type, target value, unit, dates, and status.
- Implement `record_weight`, `get_weight_history`, `update_goal`, and progress-summary services.
- Add confirmation for ambiguous writes and explicit confirmation for deletions.
- Add agent-action audit records.

Example:

```text
User: I weigh 75 kg today
Bot: I found 75.0 kg for today. Save it?
     [Save] [Cancel]
```

Acceptance criteria:

- A new weight preserves previous measurements.
- The latest valid measurement can be used by calculations.
- Progress summaries show historical trends.
- Corrections and deletion are scoped to the requesting user.

## Phase 4 — Workout conversation

Goal: let a user log common workouts naturally.

Work:

- Define a strict structured workout command schema.
- Support a small set of common formats before broad natural-language coverage.
- Normalize exercise names into the canonical taxonomy.
- Treat omitted RPE as missing; ask for it when required for a recommendation.
- Show a parsed preview and provide Save/Edit/Cancel buttons.
- Call shared workout domain services, not REST endpoints over HTTP.
- Return a recommendation after a successful save when enough data exists.

Acceptance criteria:

- `bench press 3x8 at 80 kg, RPE 8` produces a reviewable structured preview.
- Ambiguous exercise names trigger clarification rather than guessing.
- Duplicate Telegram deliveries do not create duplicate workouts.
- Existing recommendation behavior is preserved.

## Phase 5 — Private insights dashboard

Goal: provide charts and richer analysis without bloating chat responses.

Work:

- Build user-scoped dashboard routes/pages.
- Add weight, activity, workout, strength, sleep, recovery, and goal views incrementally.
- Generate opaque, short-lived, revocable dashboard access links.
- Never authorize access from a raw user ID in a URL.
- Optionally evaluate a Telegram Mini App after the external dashboard works.

Acceptance criteria:

- Telegram can send a link to the requesting user's dashboard.
- Expired or revoked links fail.
- A user cannot open another user's dashboard.

## Phase 6 — Health and activity data

### Initial bridge: Health Auto Export

- Make health ingestion user-aware rather than global.
- Introduce a pairing/setup flow or per-user ingestion credential.
- Verify actual exported metric names with a real payload.
- Support steps, walking distance, activity, sleep, HRV, resting HR, workouts, and weight as normalized metrics where available.
- Preserve idempotency by source, metric, timestamp, and user.
- Add safe historical backfill procedures.

### Long-term: native iOS HealthKit companion

- Build a native iOS app that requests only required HealthKit permissions.
- Read approved steps, walking distance, workouts, heart rate, HRV, sleep, and weight.
- Sync through authenticated user-scoped endpoints.
- Support disconnect, permission changes, data deletion, and incremental synchronization.

Acceptance criteria:

- Health data is associated with the correct internal user.
- Telegram can report activity and recovery summaries.
- Re-running an export or sync does not duplicate records.
- The product clearly tells users that Telegram itself does not access HealthKit.

## Phase 7 — Agent orchestration and evaluation

Goal: add natural-language convenience without weakening correctness.

Tools should be narrow and schema-validated:

```text
record_weight
log_workout
get_activity_summary
get_recovery_summary
get_progress_summary
get_recommendation
generate_dashboard_link
delete_user_data
```

Work:

- Add conversation and message persistence.
- Add tool-call validation and action auditing.
- Define read, write, and destructive confirmation policies.
- Build a test set of real-style workout and progress messages.
- Measure extraction accuracy and refusal behavior.
- Keep structured APIs as the source of truth and fallback.

Acceptance criteria:

- The agent never fabricates missing weight, reps, load, RPE, or health values.
- Every mutation has a traceable action record.
- Ambiguous inputs produce questions, not silent writes.
- Golden scenarios cover logging, summaries, recommendations, and recovery data.

## Phase 8 — Optional reminders

Only after the core flow is reliable:

- Opt-in daily check-ins
- Weekly progress reports
- Workout reminders
- Recovery notifications
- Goal reminders

All reminders must be configurable, rate-limited, and easy to disable.

## Validation checklist

For every implementation phase:

```bash
pytest tests/test_engine -v
pytest tests/test_api -v
pytest tests/ -v
```

Add focused tests before claiming a phase complete. Keep secrets out of fixtures unless they are explicit test values, and never use real health data in committed tests.
