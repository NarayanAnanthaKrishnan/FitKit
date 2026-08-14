# FitKit Data Schema

This document describes the current persistence model and planned additions required for the Telegram-first product. The initial Telegram identity, update-idempotency, and weight-measurement tables are implemented; a planned table is not considered complete until it is covered by migrations and tests.

## Data ownership rule

Every user-owned record must resolve to an internal `user_id`. Telegram's numeric `user_id` is an external identity used to find the internal account; it is not a substitute for internal ownership throughout the database.

Schema changes are applied through the versioned Alembic migrations in `alembic/versions/`. The application no longer creates or alters tables at startup. Apply `python -m alembic upgrade head` to a clean environment; use `stamp head` only after manually verifying an existing schema.

Never use the first row in `user_profiles` as the current user. Structured REST routes resolve an internal `user_id` from a linked Telegram identity; Telegram handlers resolve the same ownership path directly. An unlinked or unknown identity must be rejected rather than creating or selecting a default profile.

## Current tables

### `user_profiles`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | Primary key |
| `weight_kg` | `float?` | Current snapshot; nullable during incomplete onboarding; history is stored separately |
| `age` | `int` | Used by calorie estimation |
| `sex` | `text` | Current values are `male` or `female` |
| `resting_hr` | `int` | Profile value used by calorie estimation |
| `max_hr` | `int?` | Optional validation value |
| `personal_calibration_factor` | `float` | Defaults to `1.0` |

The profile should eventually contain stable account metadata separately from fitness measurements. During Telegram onboarding, profile fitness fields may be null until collected. Do not use a profile's current weight as the only record of weight progress.

### `workout_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | Primary key |
| `user_id` | `UUID` | Foreign key to `user_profiles.id` |
| `date` | `date` | Workout date |
| `session_feeling_energy` | `int` | 1–5 |
| `session_feeling_soreness` | `text` | Stored body-area tags in the current prototype |
| `session_feeling_mood` | `text?` | Optional user note |
| `watch_data_available` | `bool` | Indicates whether associated watch data was available |

### `exercise_sets`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | Primary key |
| `session_id` | `UUID` | Foreign key to `workout_sessions.id` |
| `exercise_name` | `text` | Foreign key to canonical taxonomy |
| `set_number` | `int` | Order within session |
| `reps` | `int` | Positive integer |
| `weight_kg` | `float` | Zero allowed for bodyweight-style entries |
| `rpe` | `int` | Required, 1–10 |
| `rest_seconds` | `int?` | Optional |
| `avg_heart_rate` | `int?` | Optional watch value |

Exercise names remain closed-vocabulary. Telegram parsing must normalize user language into the taxonomy and must ask for clarification when the match is ambiguous.

### `health_metrics`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | Primary key |
| `user_id` | `UUID` | Foreign key to `user_profiles.id` |
| `timestamp` | `timestamptz` | Measurement timestamp |
| `metric_type` | `text` | Canonical metric name |
| `value` | `float` | Normalized numeric value |
| `source` | `text` | Current source is `apple_watch` |

Current metric types include `hrv`, `resting_hr`, and `sleep_hours`. The model should be extended deliberately for steps, walking distance, active energy, workouts, and other activity metrics with documented units and semantics.

The unique constraint is:

```text
(user_id, metric_type, timestamp, source)
```

This enables idempotent `ON CONFLICT DO NOTHING` ingestion and safe reprocessing of overlapping exports.

### `exercise_taxonomy`

The taxonomy is seeded from `docs/exercise_taxonomy.csv`.

| Column | Type | Notes |
|---|---|---|
| `name` | `text` | Canonical primary key, for example `barbell_bench_press` |
| `display_name` | `text` | Human-readable name |
| `muscle_group` | `text` | Primary muscle group |
| `equipment` | `text` | Equipment category |

## Telegram/account entities

`telegram_identities`, `telegram_updates`, and `weight_measurements` are implemented in the first Telegram slice. Goals, conversations, actions, and dashboard access remain planned.

### Telegram identity (implemented)

Store a unique mapping from Telegram to an internal user:

```text
telegram_identities
-------------------
 id
 user_id
 telegram_user_id       unique numeric Telegram ID
 telegram_chat_id       current/private chat ID
 username               display metadata only
 first_name             display metadata
 last_name              display metadata
 created_at
 last_seen_at
```

The bot token is an application secret and must not be stored per user or in this table. It belongs in backend environment configuration.

### `weight_measurements` (implemented)

Weight is an event/history, not a field to overwrite:

```text
weight_measurements
-------------------
 id
 user_id
 weight_kg
 measured_at
 source                  telegram, health_auto_export, healthkit, or manual
 created_at
```

A new Telegram message such as “I weigh 75 kg today” creates a new measurement and preserves a previous 80 kg record.

### `fitness_goals`

```text
fitness_goals
-------------
 id
 user_id
 goal_type               weight, steps, strength, frequency, etc.
 target_value
 unit
 start_date
 target_date
 status
 created_at
 updated_at
```

### Conversations and actions

The agent will need traceability:

```text
conversations
-------------
 id
 user_id
 channel                 telegram
 external_chat_id
 status
 created_at
 last_message_at

messages
--------
 id
 conversation_id
 external_message_id
 role                    user, assistant, system, or tool
 content
 created_at

agent_actions
-------------
 id
 user_id
 conversation_id
 action_type
 input_payload
 result_payload
 status
 created_at
```

Sensitive health values should remain in structured tables. Conversation content should contain only the minimum context needed for the product and should follow the retention/deletion policy.

### Telegram update idempotency (implemented)

```text
telegram_updates
-----------------
 update_id              primary key or unique
 telegram_user_id
 received_at
 processed_at
 status
```

Telegram may retry webhook updates. Processing an existing `update_id` must not create a duplicate workout, weight measurement, or response-triggering action. The current `/delete` flow removes prior update markers for that Telegram identity and retains only the current marker without the external user ID, preserving retry protection without retaining the deleted identity in the marker.

### Dashboard access

Dashboard links should use a separate opaque access record or signed token with:

- Internal user scope
- Expiration
- Revocation capability
- No raw health data in the URL
- No authorization based only on a user ID in query parameters

## Health-data boundary

Telegram cannot request HealthKit permissions or read Apple Watch data directly. The short-term source is Health Auto Export. The long-term source is a native iOS companion app that requests explicit HealthKit permissions and syncs approved records to the backend.

Potential normalized activity types include:

```text
steps
walking_distance
active_energy
exercise_minutes
heart_rate
resting_hr
hrv
sleep_hours
weight
workout
```

Each metric needs documented units, timestamp/date-range semantics, source, and deduplication behavior before it is added to production queries.

## Fitness data rules

- RPE is required for recommendation decisions; missing RPE is not silently guessed.
- Health data is optional; missing health data results in a less specific recommendation, not a separate code path.
- Weight history is append-only by default; corrections are explicit events.
- User-owned data is always filtered by internal `user_id`.
- Destructive data deletion requires explicit `DELETE` confirmation, is scoped by internal `user_id`, and should be auditable. The current Telegram implementation retains only the current update-idempotency marker with its external user ID cleared so a webhook retry cannot recreate the deleted account.
- Health data must not be used for advertising or unrelated purposes.

See `fitness-agent-implementation-plan.md` for the migration order and acceptance criteria.
