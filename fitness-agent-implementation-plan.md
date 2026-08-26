# FitKit — Telegram-First Fitness Coach Implementation Plan

> **Planning status:** Approved direction — Safe Telegram MVP.
>
> This document is the implementation source of truth for the Telegram-first product. It records what already exists, what must be built next, why the work is ordered this way, and where an LLM may safely add value. No LLM, hosting provider, or paid integration is approved merely by appearing in this document; provider selection happens after a benchmark and privacy review.

## 1. Product definition

FitKit is a conversational fitness coach delivered primarily through Telegram. A user should be able to:

- create and maintain a private profile;
- record weight, goals, workouts, and progress in chat;
- receive activity, recovery, and training summaries;
- receive deterministic training recommendations;
- connect approved Apple Health/Watch data through a separate authorized bridge;
- open a private web dashboard for charts and deeper insights; and
- delete their account and associated data safely.

The **rule engine is the product**. The deterministic code in `engine/` owns calculations and recommendations. An LLM may interpret natural language, select from approved tools, and phrase already-computed results, but it must not invent data, make medical claims, bypass confirmation, or override the rule engine.

## 2. Non-negotiable design principles

1. **Deterministic decisions:** 1RM, overload, ACWR, volume, recovery gates, calories, and recommendations remain in `engine/`.
2. **Telegram is an adapter:** Telegram handlers translate updates into validated domain-service calls. Domain services must not depend on Telegram payloads.
3. **Explicit ownership:** Every read and write is scoped to an authenticated internal `user_id`. Never use an implicit first-user lookup.
4. **Defensive writes:** Never guess weight, exercise, reps, load, RPE, date, health values, or goals. Ask for clarification or confirmation.
5. **One graceful data path:** Health and activity data are optional. Missing data produces an explicit insufficient-data result, not a second disconnected business path.
6. **Human confirmation for mutations:** Parsed weight/workout/goal writes require a reviewable preview and confirmation. Destructive operations require explicit confirmation.
7. **Privacy by default:** Tokens, health data, conversation contents, internal IDs, and dashboard tokens must not be logged or exposed.
8. **Provider independence:** LLM access must sit behind a small model gateway so the product can switch between a frontier API, hosted open-weight inference, and a local model.
9. **Test boundaries, not just happy paths:** Security, identity, idempotency, two-user isolation, tool validation, retries, and failure modes are first-class tests.
10. **Build the smallest useful product first:** Do not start with reminders, voice, broad frontend work, fine-tuning, or autonomous agents.

## 3. Current baseline

### Already implemented

- Framework-independent engine modules for:
  - Epley estimated 1RM;
  - primary-set progressive overload;
  - acute:chronic workload ratio;
  - HRV/sleep recovery gates;
  - heart-rate calorie estimation;
  - daily training-volume aggregation; and
  - recommendation orchestration.
- PostgreSQL/SQLAlchemy models for profiles, workouts, exercise sets, health metrics, exercise taxonomy, Telegram identities, Telegram update idempotency, and weight measurements.
- FastAPI routes for structured workout logging, workout history, recommendations, health summaries, and Health Auto Export ingestion.
- Idempotent health-metric insertion.
- Canonical exercise taxonomy in `docs/exercise_taxonomy.csv`.
- Engine unit tests and API integration tests.
- Secret-protected Telegram webhook at `POST /integrations/telegram/webhook`.
- Telegram numeric-user identity mapping to internal users.
- Telegram update-idempotency records.
- Private-chat-only processing.
- `/start`, `/help`, `/delete` with explicit `DELETE` confirmation, and `/cancel`.
- Initial weight capture with historical measurement storage.
- Local development path using PostgreSQL, FastAPI, a development Telegram bot, and an HTTPS tunnel.

### Known gaps and constraints

- Structured REST routes now require the application API key plus `X-Telegram-User-Id` and resolve a linked Telegram identity to an internal user; this is an internal bridge and is not public user authentication.
- Health Auto Export still needs user-aware pairing instead of one global ingestion credential.
- Database startup no longer creates or alters tables; versioned migrations are installed. Test fixtures still use isolated metadata setup, while migration parity is checked separately in CI.
- User resolution and complete user deletion now have shared services; workout/profile/goal/conversation services remain to be extracted as those flows are added.
- Profile editing, goals, weight/goal progress summaries, and agent-action auditing now exist in the Telegram flow; conversation history and the dashboard link remain incomplete.
- Deterministic workout parsing is implemented (`/log`); free-form natural-language parsing awaits the LLM layer.
- There is no private dashboard, expiring dashboard-link system, CI workflow, deployment configuration, or staging environment.
- There is no native iOS HealthKit companion.
- No model provider, model API key, or LLM dependency is currently approved.

The REST API must remain treated as internal/local: the current API-key plus Telegram-ID bridge scopes records but does not cryptographically authenticate an end user. A trusted private network or a future signed/session-bound auth layer is required before public exposure.

## 4. Target architecture

```text
Telegram Bot API
    -> HTTPS webhook
    -> secret validation + update idempotency
    -> Telegram identity resolution
    -> command router / conversation state
    -> optional model gateway for interpretation or phrasing
    -> schema validation + confirmation policy
    -> user-scoped domain services
    -> PostgreSQL
    -> deterministic engine for calculations and recommendations
    -> Telegram response or short-lived dashboard link

Apple Health / Watch
    -> Health Auto Export initially, native iOS companion later
    -> authenticated, user-scoped ingestion
    -> normalized health/activity metrics
    -> PostgreSQL
    -> summaries and deterministic recommendations
```

Telegram cannot directly read Apple Health or display the iOS HealthKit permission prompt. A Telegram bot can link to a setup page, but HealthKit permissions require an authorized iOS application.

## 5. Priority order and implementation phases

The priority order is deliberate. Do not add broad LLM behavior or public deployment on top of implicit ownership and unsafe schema evolution.

### Priority 0 — Security, reproducibility, and development baseline

**Status:** Baseline hardening is implemented. Safe environment templates, dependency constraints, CI checks, compile/test validation, current/history secret-pattern checks, and local-operation documentation are in place; operator credential rotation and real tunnel verification remain.

**Goal:** Ensure the project can be safely developed and tested without leaking credentials or relying on one developer's machine.

**Work:**

- Verify the repository contains no bot token, webhook secret, database credential, API key, real health data, or local log output.
- Rotate any credential that has ever been exposed, even if it was later added to `.gitignore`; `.gitignore` does not remove secrets from Git history.
- Keep `.env` local and commit only a safe `.env.example` with placeholders.
- Separate development and future production Telegram bots. A bot has one active webhook, so a development bot prevents local testing from disrupting production.
- Document the local loop:
  - PostgreSQL in Docker;
  - FastAPI/Uvicorn with reload;
  - Cloudflare Tunnel or ngrok for temporary HTTPS;
  - development bot webhook registration; and
  - `/health` and webhook-status checks.
- Add structured, sanitized application logging. Never log authorization headers, bot-token URLs, full health payloads, or conversation contents by default.
- Add CI for compilation, tests, dependency installation, and secret scanning.
- Pin or constrain dependencies appropriately and record the supported Python version.

**Acceptance criteria:**

- A clean clone can be configured using `.env.example` without copying secrets from the repository.
- CI runs on every push and fails on test, compile, or secret-check failures.
- A development bot can receive `/start` through the local HTTPS tunnel.
- Stopping the backend, changing the tunnel URL, and restarting it have documented recovery steps.

### Priority 1 — Versioned database migrations and schema safety

**Status:** Migration foundation implemented. The initial Alembic schema, explicit migration commands, and a validated legacy bootstrap procedure exist; representative existing-database verification and future model migrations remain.

**Goal:** Make schema changes safe before adding more user-owned data.

**Work:**

- Introduce a versioned migration tool such as Alembic.
- Create an initial migration representing the current schema.
- Add migrations for Telegram identities, update idempotency, weight measurements, goals, conversations, agent actions, dashboard sessions, and health pairing as those features are implemented.
- Replace production reliance on startup `create_all()` and raw `ALTER TABLE` statements with explicit migration commands.
- Keep isolated test-database setup separate from production migrations.
- Separate development, test, staging, and production database configuration.
- Add foreign keys, uniqueness constraints, indexes, retention rules, and deletion behavior deliberately.
- Document backup, restore, migration, and rollback procedures.

**Acceptance criteria:**

- A new environment can be created from migrations alone.
- Migrations can upgrade a clean database and a representative existing database.
- Application startup does not silently mutate production schema.
- Every new user-owned table has an ownership path and deletion policy.

### Priority 2 — Explicit multi-user ownership and shared domain services

**Status:** Initial ownership boundary implemented; shared-service expansion and real end-user authentication remain.

**Goal:** Make every product operation resolve an internal user explicitly and consistently.

**Work:**

- Use the Telegram numeric `user_id` as the stable external identity; usernames remain display metadata only.
- Resolve Telegram identity to an internal `user_id` once per update.
- Remove implicit `select(UserProfile).limit(1)` behavior from workouts, health, recommendations, and ingestion.
- Keep the current structured REST routes internal and require the API key plus a linked `X-Telegram-User-Id` context; replace this bridge with signed/session-bound user authentication before public exposure.
- Extract reusable services for:
  - profile and onboarding;
  - weight measurements;
  - goals;
  - workout logging and history;
  - health/activity summaries;
  - recommendations;
  - dashboard access; and
  - complete user deletion.
- Make both REST routes and Telegram handlers call services directly. Do not call the local REST API over HTTP from Telegram simply to reuse code.
- Add concurrency-safe identity creation and explicit ownership checks. The current Telegram identity creation is conflict-safe, and REST ownership checks now scope every user-owned query by internal `user_id`.
- Add an audit record for every interpreted mutation, including actor, action type, validation result, confirmation state, and outcome. Do not store raw secrets in audit records.

**Acceptance criteria:**

- Two Telegram users create two distinct internal users.
- A user cannot read, modify, or delete another user's workouts, health data, goals, profile, or dashboard.
- Every user-owned query includes an explicit internal `user_id` scope.
- Deletion removes or anonymizes all registered user-owned records according to the documented retention policy.
- Existing deterministic engine tests remain unchanged and passing.

### Priority 3 — Safe Telegram MVP completion without an LLM

**Status:** Deterministic command slice implemented: `/profile`, `/goals`, `/today`, `/progress`, `/health`, inline Save/Cancel confirmations, and agent-action audit records. Outbound retry/rate-limit hardening and the deferred `/insights` dashboard link remain.

**Goal:** Deliver a useful, reliable Telegram product using deterministic commands before adding model complexity.

**Work:**

- Keep `/start`, `/help`, `/cancel`, and confirmed `/delete` reliable.
- Add `/profile` for viewing and editing known profile fields.
- Add `/goals` for creating, viewing, updating, and completing goals.
- Add `/today` for a concise activity/recovery/training snapshot.
- Add `/progress` for weight and goal trends.
- Add `/health` for available health metrics and clear insufficient-data messaging.
- Add `/insights` or a dashboard-link command only after secure dashboard sessions exist.
- Add inline buttons for Save, Edit, Cancel, Confirm, and Back where appropriate.
- Handle Telegram retries, outbound Bot API failures, rate limits, and duplicate updates safely.
- Keep command flows deterministic and observable.

**Acceptance criteria:**

- A user can complete onboarding, update weight, set a goal, view progress, and delete their data without leaving Telegram.
- Invalid or ambiguous input receives a clarification request rather than a guessed write.
- Every mutation is idempotent or protected by an idempotency key.
- Invalid webhook secrets are rejected; malformed, unsupported, group, and duplicate updates are handled safely.
- A transient Telegram API failure does not create duplicate database writes on retry.

### Priority 4 — User-aware Apple Health and activity ingestion

**Status:** Prototype ingestion exists; pairing remains.

**Goal:** Associate health/activity data with the correct Telegram user without pretending that Telegram has HealthKit permissions.

#### Initial bridge: Health Auto Export

- Design a pairing/setup flow started from Telegram.
- Replace the global ingestion credential with a per-user credential, pairing code, or other authenticated user-scoped mechanism.
- Verify a real export's metric names before relying on mappings.
- Normalize steps, walking distance, activity, sleep, HRV, resting HR, workouts, heart rate, and weight where available.
- Preserve idempotency by user, source, metric type, timestamp, and source record identity.
- Add safe historical backfill and re-run procedures.
- Provide `/health` and `/today` summaries using only metrics available for that user.
- Clearly communicate that Health Auto Export is a bridge requiring user configuration.

#### Long-term native iOS companion

- Build a separate iOS app only after the Telegram MVP is useful.
- Request only the HealthKit categories the user approves.
- Sync incrementally through authenticated user-scoped endpoints.
- Support disconnect, permission changes, partial permissions, sync errors, and data deletion.

**Acceptance criteria:**

- Health data from two users never crosses ownership boundaries.
- Re-running an export or sync does not duplicate records.
- Telegram can report activity and recovery summaries with explicit missing-data behavior.
- The product never claims that Telegram itself reads Apple Health.

### Priority 5 — Validated workout and progress conversation flows

**Status:** Core deterministic flow implemented. `/log` parses shorthand into typed data, normalizes units/exercises against the taxonomy, stores omitted RPE as `NULL`, shows a preview with inline Save/Cancel confirmation, and surfaces the deterministic recommendation after a confirmed save. `/recommend` reports the engine decision in chat. Remaining: single-field correction ("Edit") and multi-exercise logs.

**Goal:** Let users log common workouts naturally while preserving strict structured data.

**Work:**

- Define strict schemas for workouts, sets, weight measurements, goals, dates, units, RPE, and optional notes.
- Support deterministic command formats first, for example:
  - `bench press 3x8 at 80 kg, RPE 8`;
  - `squat 100 kg for 5, 5, 4`; and
  - `I weigh 75 kg today`.
- Normalize units and exercise names against `docs/exercise_taxonomy.csv`.
- Treat omitted RPE as missing; never invent it.
- Show a preview before saving:

  ```text
  I understood:
  Bench press — 3 sets × 8 reps — 80 kg — RPE 8
  Save this workout?
  [Save] [Edit] [Cancel]
  ```

- Allow correction of one field without restarting the whole flow.
- Call the shared domain service after confirmation.
- Return a deterministic recommendation only after a successful save and only when sufficient data exists.

**Acceptance criteria:**

- Ambiguous exercise names trigger clarification.
- Invalid units, dates, reps, weights, or RPE values are rejected clearly.
- Duplicate Telegram deliveries do not create duplicate workouts or weight measurements.
- Existing recommendation behavior remains authoritative and unchanged.

### Priority 6 — Private insights dashboard

**Status:** Not complete.

**Goal:** Move charts and detailed trends out of chat while keeping access private.

**Work:**

- Build user-scoped dashboard routes/pages incrementally.
- Start with weight and goals, then workouts/strength, activity, sleep, and recovery.
- Generate opaque, short-lived, revocable dashboard access links.
- Never authorize a dashboard from a raw user ID in a URL.
- Add session expiration, revocation, rate limiting, and minimal access logging.
- Use Telegram for the link and the dashboard for visual exploration.
- Evaluate a Telegram Mini App only after the external dashboard's security model works.
- Netlify may host a future frontend; it is not the FastAPI/PostgreSQL backend.

**Acceptance criteria:**

- Telegram can send a dashboard link for the requesting user.
- Expired, revoked, malformed, and reused links fail safely.
- A user cannot open another user's dashboard.
- Dashboard values match the same user-scoped services used by Telegram.

### Priority 7 — LLM pilot and controlled agent orchestration

**Status:** Deliberately deferred until the deterministic foundation is ready.

**Goal:** Add natural-language convenience without turning the model into the source of truth.

The LLM should be introduced as a **bounded interpreter and formatter**, not as an autonomous fitness decision-maker.

**Work:**

- Define the provider-neutral model-gateway contract and allowlisted tool schemas.
- Build the synthetic evaluation set before selecting a provider or model.
- Benchmark one affordable frontier API against one hosted or local open-weight model.
- Start with read-only intent classification and extraction.
- Add write-capable parsing only after preview/confirmation flows and audit records exist.
- Add deterministic fallback behavior when the model times out, fails validation, exceeds budget, or is disabled.
- Add redacted usage, latency, error, fallback, and cost metrics.
- Keep local/offline benchmarking separate from any external-data pilot.

**Acceptance criteria:**

- The model cannot access the database or execute tools outside the allowlist.
- Invalid structured output is rejected and never reaches a domain write service.
- No weight, workout, goal, or destructive action is saved without the existing confirmation policy.
- The no-LLM command path remains fully usable.
- Local model benchmarking may happen after Priority 5; an external-model pilot requires the staging, privacy, and operational gates in Priority 8 first.
- The selected model meets the agreed extraction, refusal, latency, and cost thresholds on the versioned evaluation set.

### Priority 8 — Deployment and staging hardening

**Status:** Not complete.

**Goal:** Create a stable staging environment before real-user or production use.

**Work:**

- Add a reproducible deployment artifact, such as a Dockerfile and documented start command.
- Deploy FastAPI and PostgreSQL using separate managed services or a deliberately documented equivalent.
- Configure environment variables through the host's secret manager, not repository files.
- Use a stable HTTPS backend URL for the staging bot.
- Keep local, staging, and production Telegram bots and databases separate.
- Add `/health` liveness checks, error monitoring, sanitized structured logs, backups, restore tests, and migration execution during deploy.
- Set resource limits, request timeouts, Telegram outbound timeouts, and rate limits.
- Document webhook registration and rollback.
- Keep the production bot disabled until ownership, deletion, privacy, and monitoring acceptance criteria pass.

**Acceptance criteria:**

- Staging survives a restart without losing schema or data.
- Telegram webhook status, application logs, database health, and outbound delivery failures are observable without exposing secrets.
- A rollback procedure is tested.
- Staging cannot access production data.

### Priority 9 — Optional reminders and native integrations

Only after the core product is reliable:

- opt-in daily check-ins;
- weekly progress reports;
- workout reminders;
- recovery notifications;
- goal reminders; and
- native iOS HealthKit synchronization.

All reminders must be configurable, rate-limited, timezone-aware, and easy to disable. Voice, broad fine-tuning, and complex periodization remain later experiments rather than MVP requirements.

### Priority 10 — Personalized coaching: nutrition, hydration, and tailored nudges

**Status:** Planned — after LLM pilot is proven. No code exists.

**Goal:** Give every user a per-user daily coaching loop around food and hydration that is personalized from their own profile, goals, history, and explicit preferences — without letting the model invent nutritional facts.

**Two halves, kept separate:**

- **Deterministic core in `engine/`:** hydration target (~30–35 ml/kg body weight, adjusted by recent training volume and goal type); simple calorie/macro targets derived only from profile + active goal; nudge triggers as explicit rules (e.g., no `hydration_logs` entry for N hours inside the user's waking window, no meal logged by a cutoff time). Missing data produces an explicit insufficient-data result, never a guessed value. Deterministic, testable, and cheap.
- **LLM-bounded surface via the gateway:** parse messy food/water text such as `2 eggs + toast` or `had ~300ml water` into a typed `log_food` / `log_water` candidate, then Pydantic validation → preview/confirmation → domain service. Phrase nudges and summaries from engine-computed facts only.

**Work:**

- Add `user_preferences` (units, timezone, wake window, `nudges_enabled`, `quiet_hours`), `food_logs`, and `hydration_logs` tables (see `docs/data_schema.md` planned tables). Food names are open vocabulary (unlike `exercise_taxonomy`) — store verbatim `description`; `calories_kcal` stays NULL unless the user explicitly confirms an estimate. Never auto-fill calories from a nutrition DB.
- Extend `agent_actions` with `log_food` and `log_water` types, reusing the existing confirmation-token and TTL policy.
- Keep `engine/` free of LLM/Telegram imports; keep domain services as the single write path (both `/log` and `/logfood` call them).
- Proactive nudges are opt-in only (extends Priority 9 constraints: configurable, rate-limited, timezone-aware, one-tap disable via `/preferences` or `/cancel`). The bot never messages first unless enabled.
- Personalization inputs: profile completeness, active goals, weight trend, workout frequency, recent meals/water, explicit preference settings.
- Add `/logfood`, `/logwater`, `/preferences`, and enriched `/today` (hydration progress ring) commands; nudges reuse the same Telegram delivery retry/rate-limit path.

**Acceptance criteria:**

- Two-user isolation for `food_logs`, `hydration_logs`, `user_preferences`; deletion removes them with the rest of user-owned data.
- Every mutation audited via `agent_actions`; no food/water write without preview + confirmation.
- Nudges are disabled by default, rate-limited, timezone-aware, and stopped by a single disable command; a user who never opts in receives zero proactive messages.
- No-LLM deterministic path (`/logfood 2 eggs toast`, `/logwater 500 ml`) still works when the gateway is disabled.
- Missing calories/entry data is never guessed; estimates are explicitly labeled and require confirmation.

## 6. LLM strategy: where it adds value

### Recommended role

Use an LLM where language is messy and rules are stable:

1. **Intent classification**
   - distinguish a workout log, weight update, goal update, progress question, recovery question, dashboard request, help request, or unsupported topic;
   - route exact commands without calling a model when possible.

2. **Structured extraction**
   - convert shorthand such as `bench 80 3x8 rpe 8` into a typed candidate payload;
   - extract units, dates, set counts, reps, weight, RPE, and notes;
   - preserve omitted fields as `null` rather than guessing.

3. **Exercise-name normalization**
   - map slang such as `deads` or `incline db press` to a canonical taxonomy candidate;
   - return multiple candidates or ask a question when confidence is insufficient;
   - never create arbitrary exercise records.

4. **Conversation repair**
   - understand corrections such as `same workout but 82.5 kg`;
   - track only the minimum required pending state;
   - keep the final write behind schema validation and confirmation.

5. **Natural-language presentation**
   - turn deterministic results into concise, friendly Telegram messages;
   - explain why a recommendation was produced using only facts supplied by the engine;
   - avoid changing numeric values, severity, or training decisions.

6. **Read-only summaries**
   - summarize user-scoped service results such as weight trend, recent activity, or recovery;
   - use precomputed aggregates rather than passing an entire database history to the model.

7. **Support and education**
   - answer general fitness questions with bounded, reviewed guidance;
   - distinguish general education from medical advice;
   - escalate or recommend professional care for concerning symptoms instead of diagnosing.

### What the LLM must not do

- calculate or override ACWR, overload, recovery gates, calories, or recommendations;
- directly query PostgreSQL;
- directly execute arbitrary Python, SQL, HTTP, or Telegram actions;
- save a weight, workout, goal, or deletion without the required validation and confirmation;
- infer missing RPE, weight, reps, dates, health values, or user intent;
- expose one user's data in another user's context;
- read HealthKit directly;
- make medical diagnoses or unsafe treatment claims; or
- become a required dependency for exact commands and core data access.

## 7. Proposed LLM architecture

```text
Telegram update
    -> identity + idempotency checks
    -> deterministic command handling where possible
    -> model gateway only for supported free text
    -> structured intent/tool candidate
    -> Pydantic/schema validation
    -> confidence and ambiguity policy
    -> preview + user confirmation for writes
    -> user-scoped domain service
    -> deterministic engine for calculations
    -> optional model formatting of the result
    -> Telegram response
```

The model gateway should provide:

- a provider-neutral request/response interface;
- model name, timeout, token limits, and temperature/configuration from environment;
- structured-output or tool-call validation;
- retry and fallback behavior;
- usage and latency metrics without storing sensitive prompt text by default;
- a kill switch to disable the LLM and fall back to deterministic commands; and
- a per-user and global budget/rate limit.

The LLM receives only the minimum context needed for the current operation:

- current user intent and pending conversation state;
- validated profile fields needed for that operation;
- small, precomputed summaries when required; and
- the allowed tool schema and confirmation rules.

It should not receive the entire workout history, raw health payloads, database identifiers, or unrelated conversations.

## 8. Model options and recommended rollout

Do not choose a model by benchmark reputation alone. Benchmark the exact FitKit tasks: intent routing, structured extraction, taxonomy mapping, refusal behavior, tool selection, latency, and cost.

### Option A — Frontier model API

**Best initial use:** development benchmark and first controlled pilot.

**Advantages:**

- strongest structured extraction and tool-use reliability;
- fastest time to a useful prototype;
- no GPU operations or model serving work;
- easy to compare multiple models behind the gateway.

**Tradeoffs:**

- usage cost grows with message volume and context size;
- health and conversation data leave the application infrastructure;
- provider retention, residency, training-use, and outage policies must be reviewed;
- provider-specific tool-calling behavior can create lock-in if the gateway is not kept neutral.

### Option B — Hosted open-weight inference

**Best initial use:** cost/privacy comparison after the task dataset exists.

**Advantages:**

- open-weight models may be cheaper at sustained volume;
- some providers offer OpenAI-compatible interfaces and fast inference;
- easier model switching than operating GPUs ourselves;
- possible contractual privacy advantages over free consumer endpoints.

**Tradeoffs:**

- quality and structured-output reliability vary by model and serving provider;
- free tiers may have restrictions, rate limits, queueing, or prompt-use policies unsuitable for health data;
- hosted inference is still third-party processing, not the same as self-hosting;
- provider availability and exact pricing can change.

Potential candidates should be treated as a shortlist to benchmark, not a commitment: current instruction-tuned small/medium open-weight families (for example, Llama, Qwen, Mistral, or equivalent) through a privacy-reviewed inference provider.

### Option C — Self-hosted/local open-weight model

**Best initial use:** local development, privacy-sensitive deployments, or later scale when traffic justifies operations.

**Advantages:**

- prompts and responses can remain inside controlled infrastructure;
- predictable marginal token cost after infrastructure is paid for;
- no dependency on a third-party model API for availability;
- local inference can be useful for development and automated tests.

**Tradeoffs:**

- GPU or capable hardware costs, maintenance, monitoring, upgrades, and cold starts;
- lower-quality small models may require more clarification and stronger post-validation;
- serving, concurrency, quantization, security, and backups become our responsibility;
- at low traffic, an always-on GPU may cost more than a small API bill.

A practical local experiment can use a small instruct model through a local runtime such as Ollama or an equivalent server, but local success does not prove production latency or quality.

### Recommended decision

1. Start with **no LLM** for exact commands and core MVP flows.
2. Build the deterministic tool/service contracts and evaluation dataset first.
3. Run a low-volume benchmark against one affordable frontier model and one hosted or local open-weight model.
4. Use the cheapest model that meets the extraction/refusal/latency thresholds.
5. Keep a frontier fallback only for low-confidence cases if the cost budget permits.
6. Re-evaluate self-hosting only when usage, privacy requirements, or economics justify GPU operations.

Selected provider for the pilot: **Groq, model `qwen/qwen3-32b` (Qwen3 27–32B class; exact ID to be confirmed in the Groq console as `qwen/qwen3-32b` or equivalent `qwen3-30b-a3b`)** — chosen for low latency, OpenAI-compatible JSON/tool interface, and negligible cost at pilot volume (few users × <20 msgs/day). The gateway remains provider-neutral so a frontier fallback can be added without code changes. Provider credentials must never be committed, and the external-model release gate below still applies; local synthetic-data benchmarking proceeds without external-processing approval.

### External-model release gate

An external model may process user messages only after all of the following are documented and approved:

- provider API/business terms and training-use policy;
- retention, deletion, encryption, subprocessor, and data-region behavior;
- user notice/consent and an opt-out or no-LLM path;
- redaction/minimization rules for health and profile data;
- model outage, timeout, budget-exhaustion, and kill-switch behavior;
- staging isolation from production data; and
- an owner for monitoring provider changes and costs.

Local model benchmarking can proceed without this external-processing approval when it uses synthetic data or stays inside the developer's controlled environment.

## 9. LLM cost model and controls

The correct cost depends on actual messages, context length, model, output length, retries, and provider pricing. Do not assume a free tier will remain free or permit health data.

### Cost equation

```text
monthly LLM cost
= input tokens / 1,000,000 × input price
+ output tokens / 1,000,000 × output price
+ fixed hosting/inference cost
+ observability/storage cost
+ retry/fallback overhead
```

Self-hosted inference replaces token price with infrastructure, operations, and capacity cost. At low usage, a metered API is often cheaper; at sustained usage or stricter privacy requirements, hosted open-weight or self-hosting may become more attractive.

### Required cost controls

- Handle exact commands without an LLM.
- Use a small/cheap model for intent and extraction; reserve a stronger model for low-confidence fallback.
- Cap input context and output tokens.
- Pass compact, precomputed summaries instead of full history.
- Use deterministic response templates for common commands.
- Cache stable instructions and taxonomy context when the provider supports safe prompt caching.
- Batch non-urgent weekly summaries rather than generating them interactively.
- Avoid automatic multi-step agent loops; use one model call per user turn by default.
- Set per-user daily limits and a global monthly spend ceiling.
- Track token usage, model, latency, errors, fallback rate, and estimated cost per successful action.
- Alert before the budget is exhausted and fail gracefully to deterministic flows.
- Do not log full prompts/responses just to measure cost; store redacted metadata.

### Cost benchmark procedure

Before choosing a model, replay the same versioned evaluation set through each candidate and record:

1. total input and output tokens;
2. number of requests, retries, and fallback calls;
3. successful structured actions, clarification actions, and rejected outputs;
4. estimated cost at the provider's current prices;
5. cost per successful parsed action, not just cost per request;
6. p50/p95 latency and timeout rate; and
7. projected monthly cost at several realistic usage levels.

Run the benchmark with synthetic data first. Re-check provider pricing, limits, retention, and free-tier conditions immediately before integration because they can change. A cheaper model that needs retries or produces unsafe parses is not cheaper in practice.

### Example rollout budget policy

The exact monetary values should be configured after observing real traffic, but the policy should include:

- a development monthly ceiling;
- a staging ceiling;
- a production hard limit;
- a maximum output-token limit per operation;
- a maximum number of retries;
- a fallback disable switch; and
- an explicit behavior when the limit is reached: continue commands, pause free-text parsing, and tell the user how to use structured commands.

## 10. Privacy and safety requirements for an LLM

Before sending health or conversation data to any external model provider:

- document what data is sent and obtain appropriate user notice/consent;
- minimize and redact data wherever possible;
- use provider API/business terms rather than consumer chat products;
- verify training-use, retention, deletion, region, encryption, and subprocessors;
- provide a way to disable model processing;
- avoid sending raw Health Auto Export payloads;
- do not include Telegram tokens, webhook secrets, dashboard tokens, or internal IDs;
- support deletion of stored prompts, outputs, traces, and embeddings if any are created; and
- review whether the product's health-related data handling requires additional legal/privacy work before public launch.

The free endpoint with the lowest price is not automatically acceptable for private health data.

## 11. LLM evaluation plan

Create a versioned, synthetic-first evaluation set before selecting a model. Do not commit real health or private conversation data.

### Dataset categories

- exact commands that should bypass the LLM;
- simple weight entries in kg and lb;
- ambiguous or missing weight/date/unit inputs;
- workout shorthand and multi-set logs;
- exercise aliases and ambiguous taxonomy matches;
- corrections to a pending preview;
- requests for progress, activity, recovery, and recommendations;
- insufficient-data cases;
- duplicate messages and retries;
- prompt injection attempts such as requests to ignore confirmation rules;
- unrelated, unsafe, or medical questions; and
- destructive actions requiring confirmation.

Start with at least 100–200 synthetic examples, then expand using redacted, consented production-like examples only if allowed.

### Metrics and release gates

Measure separately:

- intent accuracy;
- exact structured-field accuracy for exercise, date, sets, reps, weight, unit, and RPE;
- canonical taxonomy match accuracy;
- correct clarification/refusal rate;
- tool-selection accuracy;
- no-write-without-confirmation rate;
- user-isolation and prompt-injection tests;
- p50/p95 latency;
- token usage and estimated cost per successful action; and
- fallback/error rate.

A model is not production-ready if it is merely fluent. It must meet the field-accuracy and safety gates, with zero tolerance for cross-user data access or unconfirmed destructive writes.

## 12. Testing and validation checklist

Every implementation phase must add focused tests before being marked complete.

### Engine tests

```bash
pytest tests/test_engine -v
```

Keep `engine/` free of FastAPI, SQLAlchemy, Telegram, and model-provider imports.

### API and ownership tests

```bash
pytest tests/test_api -v
pytest tests/ -v
```

Cover:

- migrations and clean-database startup;
- two-user data isolation;
- explicit authenticated ownership;
- health ingestion pairing and idempotent backfill;
- deletion across every user-owned table;
- dashboard token expiration/revocation; and
- outbound Telegram failure behavior.

### Telegram adapter tests

Use fake Telegram updates and mocked outbound Bot API calls. Cover:

- valid and invalid webhook secret;
- private chat versus group chat;
- malformed and unknown updates;
- duplicate `update_id`;
- concurrent identity creation;
- `/start`, `/help`, `/cancel`, `/delete` confirmation;
- profile, weight, goal, summary, and workout flows;
- Telegram API timeout/rate-limit/retry behavior; and
- no duplicate database writes.

### LLM tests

Model calls must be mocked in normal CI. Cover:

- valid structured output;
- invalid schema output;
- missing fields;
- ambiguous exercise mapping;
- prompt injection;
- tool calls outside the allowlist;
- no confirmation;
- timeout/provider outage;
- token-budget exhaustion;
- fallback to deterministic commands; and
- cross-user context isolation.

Use a small opt-in integration suite for real provider benchmarks; never make the normal test suite depend on a paid API or network availability.

## 13. MVP cut line

The first public pilot should stop here:

- secure Telegram webhook and identity mapping;
- migrations and explicit multi-user ownership;
- profile and weight history;
- goals and progress summaries;
- user-aware Health Auto Export pairing, if health data is included in the pilot;
- structured workout logging with preview/confirmation;
- deterministic recommendations;
- deletion and privacy controls;
- automated tests, logs, CI, backups, and staging; and
- optional, tightly bounded LLM parsing only after the deterministic flows pass evaluation.

The following are **not required for the first pilot**:

- a fully autonomous agent;
- broad medical or nutrition advice;
- voice input;
- fine-tuning;
- native iOS HealthKit synchronization;
- complex periodization;
- social features;
- reminders;
- personalized food/hydration logging and proactive nudges (Priority 10); or
- a polished dashboard beyond the minimum private progress view.

## 14. Delivery milestones

### Milestone A — Safe foundation

Priorities 0–2 complete: clean secrets, reproducible tests/CI, migrations, explicit ownership, shared domain services.

### Milestone B — Useful Telegram MVP

Priority 3 complete: profile, goals, progress, activity/recovery summaries, safe deletion, resilient Telegram delivery.

### Milestone C — Data and workout loop

Priorities 4–5 complete: paired health ingestion, validated workout conversation, deterministic recommendation after save.

### Milestone D — Private insights and staging

Priorities 6 and 8 complete: dashboard, expiring links, stable staging deployment, observability, backups, and rollback.

### Milestone E — Measured LLM pilot

Priority 7 complete: provider benchmark, bounded model gateway, confirmation policy, cost controls, privacy review, and evaluation gates.

### Milestone F — Expansion

Priority 9: reminders, native HealthKit, richer integrations, and further model work only after pilot evidence justifies them.

### Milestone G — Personalized coaching (post-LLM)

Priority 10 complete: `user_preferences`, `food_logs`/`hydration_logs`, deterministic hydration/calorie targets in `engine/`, opt-in nudge scheduler, and Groq-phrased summaries — all behind the same preview/confirmation and budget policy proven in Milestone E.

## 15. Definition of done for a phase

A phase is complete only when:

1. implementation is covered by focused unit/integration tests;
2. two-user isolation and idempotency are tested where applicable;
3. migrations are included for schema changes;
4. failure and retry behavior is documented;
5. secrets and health data remain out of source control and logs;
6. the deterministic engine's behavior is unchanged unless explicitly approved;
7. acceptance criteria pass locally and in CI;
8. operational or rollback instructions exist for deployable changes; and
9. this plan and related documentation are updated to reflect actual status.

## 16. Immediate next implementation step

The deterministic Telegram slice is now complete: onboarding, weight, goals, profile, `/today`/`/progress`/`/health`, `/log` (workout logging with preview/confirm and missing-RPE support), `/recommend`, outbound retry/rate-limit handling, agent-action audit records, and inline confirmations. Health Auto Export pairing (Priority 4) is deliberately deferred.

The next product slice is the **LLM layer (Priority 7)** on **Groq `qwen/qwen3-32b`**: a provider-neutral model gateway (with Groq as the pilot backend), a synthetic evaluation set, bounded intent/extraction with the existing preview/confirmation policy, and a deterministic fallback so exact commands work with no model. Benchmark the Groq model on the eval set; keep a frontier fallback only if low-confidence cases justify it. The deferred `/insights` dashboard link remains Priority 6, and **personalized food/hydration + nudges (Priority 10) follows Milestone E** once the gateway is proven.

Keep the structured REST bridge private until signed/session-bound end-user authentication replaces the caller-supplied Telegram-ID context. Do not add a broad LLM chat loop or public production deployment before the deterministic flows and privacy boundaries are complete.
