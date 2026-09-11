# Private-beta implementation and rollout

The current milestone is a reliable private beta that helps users improve their existing routines. Weight, age, sex, health data, and AI are optional. Full program generation and proactive reminders are outside this milestone.

## Implemented

| Shortcoming | Resulting behavior | Main evidence |
|---|---|---|
| Telegram replies depended on the webhook transaction | Receipt commits before acknowledgement; leased worker processing commits domain writes and outbound jobs together | `test_beta_reliability.py`, queue and worker services |
| Duplicate/overlapping confirmations could repeat writes | Per-user ordering and row locks; completed/expired/editing previews cannot execute again | Concurrent confirmation and replay tests |
| Prefix matching accepted mixed confirmation messages | Only exact `yes`/`save` or an active button approves ordinary previews; deletion needs exact `DELETE` | Confirmation unit tests and Telegram integration tests |
| Edited previews left old buttons usable | Successful edits rotate tokens; per-set editing and revision-checked saved-workout corrections | Workout edit and stale-revision tests |
| LLM schemas and evidence checks were permissive | Typed bounded intent payloads; values bound to source exercise/units; explicit missing RPE; ambiguous dates clarified | Gateway unit tests and adversarial evaluation fixtures |
| AI availability implied consent; budgets lived in memory | Separate per-user consent; minimal context; database reservations per UTC day and attempted call | Consent and concurrent budget tests |
| Health retries could create new measurements | Stable batch identity, payload conflict detection, duplicate counts, validation-only requests | Ingestion and pairing tests |
| Calendar queries used server time or lifetime counts | IANA timezone boundaries, DST support, Monday-based weekly goals, bounded historical queries | Calendar, weekly reset, and history tests |
| Recommendations assumed a universal rep target | Per-exercise targets; explicit insufficient data; load increments only when deterministically supported | Engine tests and scoped target regression |
| Recovery holds could hide deload or missing data | Recovery can suppress an increase while preserving deload/insufficient decisions | Engine boundary tests |
| Health sources and sleep totals could be silently combined | Conflicting daily sources/totals are excluded and reported; provenance accompanies usable readings | Health conflict regression |
| Runtime package lacked required client/data assets | Runtime HTTP/crypto/timezone dependencies and packaged vocabulary; non-root image and migration-first startup | Docker build and runtime smoke checks |
| Deployment/restore behavior was undocumented | TLS ingress template, production allowlist, readiness, aggregate metrics, operator retry, encrypted restore drill | Operations runbook and backup utility |
| Everyday use required slash-command syntax | Feature-gated local natural routing, focused encrypted follow-ups, safe preview interleaving/replacement, and optional AI-polished openers | Conversation unit and Telegram integration tests |
| Conversation quality lacked privacy-safe signals | Content-free interaction outcomes/ratings plus separately disclosed, encrypted feedback samples that expire after 30 days | Interaction service, operator metrics, feedback callbacks |
| Conversational planning did not reliably finish the user's task | Encrypted routine-review state, explicit turn order, source-backed exercise review, local acknowledgements, and task-stage metrics | Conversation services, typed LLM intents, transcript replay tests |

## Release gates

Code checks must pass before deploying: all engine/unit/API tests, migration parity and empty-database rollback, production image build, container smoke flow, secret scan, and an encrypted restore drill against synthetic data. Record actual results in the release review; do not infer production readiness solely from test counts.

Before inviting users, configure the host, HTTPS certificates, dedicated bot webhook, invitation IDs, secrets, backup retention, and alerts. Run the live synthetic Groq benchmark if AI will be enabled. Confirm one real, consented phone payload's timestamp, units, metric names, duplicate count, and skipped count. Validation-only requests must not create synthetic health records in a user's account.

Start with a small invited cohort. Observe seven consecutive days with:

- No duplicate workout/weight writes or ownership violations.
- No unexplained terminal jobs; investigate oldest queue age above 120 seconds.
- Working confirmation, correction, cancellation, account deletion, and expired-link behavior.
- Provider fallback still allowing deterministic commands; AI budgets respected.
- At least one backup restore verified and a recorded rollback procedure.
- Reviewed parsing failures and user feedback using consented, redacted examples.

Real deployment, live provider quality, real phone sync, alert delivery, backup scheduling, and seven-day observation require external configuration or elapsed operation. They are not completed by a local code change.

## Local verification — 2026-09-08

- Full suite: **210 passed** (103 engine/unit tests and 107 PostgreSQL integration tests). The retained local report is `artifacts/private-beta-tests.xml` (ignored by Git).
- Alembic: upgrade, metadata comparison, empty-database downgrade, re-upgrade, and comparison passed through `20260908_0010` on `fitkit_beta_migrations`; revisions `20260908_0011`, `20260910_0012`, and `20260910_0013` add encrypted conversation context/state, privacy-safe interaction feedback, and confirmed preference memory, and require the same release migration check.
- Docker: final image built; installed-package smoke flow passed with mocked external transport, durable receipt, confirmed workout, delivery, readiness, and production route restrictions. Compose configuration validated.
- Offline evaluation: 15 adversarial candidate checks and 10 routing checks passed. No live Groq evaluation was performed.
- Backup: an encrypted synthetic snapshot restored into a new database with matching schema, 118 taxonomy entries, one user and one workout. The temporary drill key was discarded; this is verification evidence, not a recoverable application backup.
- Secret pattern scan (working tree and available Git history), dependency consistency, compilation and whitespace checks passed.

An intervening test run could not connect because Docker Desktop was stopped. PostgreSQL was restarted and the complete suite above then passed. No application database was migrated, restored over, or used by the tests.

## Conversation-v2 local verification — 2026-09-10

- Full suite: **236 passed** against the dedicated migration-backed test database.
- Natural conversation unit/integration coverage includes no-slash workout logging, missing-load follow-up, read-only questions during previews, natural corrections, exact deletion confirmation, and disclosed encrypted feedback retention.
- Offline evaluation: **15/15** extraction-boundary checks and **10/10** routing-bypass checks passed. No live provider evaluation was performed.
- Compilation and the Alembic single-head check passed at `20260910_0012`; encrypted preference memory and the task harness advance the current head to `20260911_0014` and require the same release checks.

## Subsequent development

1. **Beta feedback and data quality:** measure clarification/correction rates, improve source-backed parsing, test real exporter payloads, and resolve any operational incidents before expanding scope. Add source configuration only if users need multiple bridges.
2. **Nutrition and hydration:** introduce user-owned logs and explicit units, editable previews, deletion coverage, and deterministic targets with transparent assumptions. Do not invent nutritional values from a food name or prescribe a target without the required inputs.
3. **Opt-in nudges:** only after reliable delivery, add consent, quiet hours, user timezone, frequency caps, cancellation, and idempotent scheduled jobs. Test DST and duplicate scheduling.
4. **Native HealthKit companion:** after the Telegram beta proves useful, implement explicit permissions, minimal synchronization, source identifiers, revocation, and background-sync testing on real devices.
5. **Broader coaching:** evaluate routine templates or program generation separately from existing-routine progression, using measurable product demand and reviewed deterministic rules. Voice, fine-tuning, and a broad frontend remain deferred.
