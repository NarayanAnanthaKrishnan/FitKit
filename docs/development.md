# Local development

Use Python 3.12 and PostgreSQL 16. Copy `.env.example` to `.env`; fill in local credentials and a separate development bot. Keep `FITKIT_PRODUCTION=0` and `LLM_ENABLED=0` initially. Never point a production bot's webhook at a laptop.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -c constraints.txt -e ".[dev]"
```

Generate `FITKIT_QUEUE_KEY` once with `Fernet.generate_key()` and store it in `.env`. Generate a different `FITKIT_MEMORY_KEY` before testing durable preference memory; development falls back to the queue key only for compatibility. The API and worker need the same keys. The [operations guide](operations.md) explains key handling. `DATABASE_URL` should use `127.0.0.1` for a local database; this avoids machine-specific localhost resolution problems.

Start PostgreSQL before migrating. `bash scripts/devdb.sh` creates/starts the local `fitkit-postgres` container, ensures `fitkit` and `fitkit_beta_test` exist, and upgrades the local application database. It refuses to stamp an unversioned schema automatically. Its password is for local development only.

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Run the worker in another terminal:

```powershell
.venv/Scripts/python.exe -m api.worker
```

`GET /health` is API liveness. `GET /ready` also requires the current migration, packaged taxonomy, and a worker heartbeat less than 90 seconds old. A webhook success means the receipt is durable; interpretation and replies happen asynchronously. The API alone will not answer Telegram messages.

All legacy REST calls require `X-API-Key` and `X-Telegram-User-Id` for an existing account. This is a local/internal bridge, not public authentication. Production blocks the workout, recommendation, health-summary, documentation, and internal-metrics routes. Paired ingestion uses `X-Health-Pairing-Token`; shared-key ingest is disabled by default.

To exercise the natural-first router, set `TELEGRAM_CONVERSATION_V2=1`; slash commands remain available. Common complete requests route locally, while missing workout load becomes a short encrypted follow-up. To exercise optional AI interpretation and reply openers too, configure `GROQ_API_KEY`, set `LLM_ENABLED=1`, then explicitly enable flexible chat in the bot. Turning it off stops future provider interpretation immediately when processed and clears retained conversation turns. Missing configuration fails startup instead of silently enabling an incomplete deployment.

| Setting | Default |
|---|---|
| `TELEGRAM_CONVERSATION_V2` | `0`; staged rollout for the natural-first conversation router |
| `GROQ_MODEL` | `openai/gpt-oss-120b` |
| `LLM_TIMEOUT_MS` | 8000, total deadline including up to two attempts |
| `LLM_MAX_OUTPUT_TOKENS` | 1024 |
| `LLM_TEMPERATURE` | 0.2 |
| `LLM_DAILY_LIMIT_PER_USER` | 50 attempts per UTC day |
| `LLM_GLOBAL_DAILY_LIMIT` | 500 attempts per UTC day |
| `ACTION_CONFIRM_TTL_SECONDS` | 900 |
| `DASHBOARD_LINK_TTL_SECONDS` | 900 |

Limits must be positive. Every attempted provider request consumes a persisted reservation, including failed requests and retries. Budgets work across workers and naturally reset at UTC midnight. User-local workout days are independent of that accounting boundary.

## Verification

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://postgres:fitkit@127.0.0.1:5432/fitkit_beta_test'
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m pytest tests/test_engine tests/test_unit -q
.venv/Scripts/python.exe scripts/eval_groq.py --offline
.venv/Scripts/python.exe -m pip check
docker build -t fitkit:local .
```

API fixtures require a database name ending in `_test`. They apply Alembic migrations, truncate user data between tests, seed the packaged taxonomy, and mock external calls. Never run them against application data. The fixture's Telegram client drains the worker for convenience; reliability tests use the raw receipt path to test asynchronous behavior.

The live synthetic benchmark is `python scripts/eval_groq.py --model openai/gpt-oss-120b`. It uses only `tests/eval/cases.jsonl`, makes paid provider calls, and reports intent, payload, clarification, safety, fallback, latency, and token counts. The offline run tests candidate fixtures in `tests/eval/boundaries.jsonl` and does not claim model accuracy. Integration tests establish database confirmation behavior.

## Schema and taxonomy changes

Create explicit Alembic revisions and run upgrade/check/downgrade/upgrade/check against a disposable database. Startup seeds taxonomy but never changes schema. Existing installations at revision `20260822_0008` upgrade normally. Unversioned legacy databases require a backup and schema inspection; the old bootstrap utility fails closed if metadata differs and is not a general migration substitute.

The runtime vocabulary is `api/data/exercise_taxonomy.csv`; keep `docs/exercise_taxonomy.csv` identical for readers. Tests check parity. Do not silently add exercises from a parser or provider response.
