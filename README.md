# FitKit — Telegram Fitness Coach

FitKit helps people log and improve an existing training routine. Deterministic Python rules decide progression; optional Groq interpretation turns free text into validated previews. Profile details and connected health data are optional.

The private-beta implementation includes:

- Private-chat Telegram identity, a production invitation allowlist, and user-scoped services.
- Durable encrypted inbound and outbound jobs, per-user ordering, leases, retry limits, and replay protection.
- Exact confirmation, expiring previews, per-set editing, revision-checked workout corrections, and confirmed account deletion.
- Optional profile setup; timezone, kg/lb display, and separate per-user AI consent in `/preferences`.
- Exercise-specific rep targets and optional load increments in `/target`. Recommendations report missing inputs and use one path with or without health data.
- Weight history, weekly goals, exercise progress, recovery provenance, and private expiring dashboard links.
- User-paired health ingestion with stable batch IDs, duplicate reporting, and a validation-only endpoint.
- Alembic migrations, a non-root Docker image, separate worker, TLS proxy configuration, local operator metrics, and encrypted backup tooling.
- A feature-gated natural-first Telegram router for common requests, focused follow-ups, flexible pending previews, metadata-only interaction quality metrics, and explicitly consented 30-day feedback samples.

```text
Telegram -> verified webhook -> durable receipt -> worker
             -> validated domain services -> PostgreSQL + engine
             -> durable outbound job -> Telegram
```

## Local development quick start

These commands assume Windows PowerShell, Python 3.12, Docker Desktop, and Git Bash are installed. From the repository root, create the environment once:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"
```

Fill in the development values in `.env`. Keep `FITKIT_PRODUCTION=0`; set `TELEGRAM_CONVERSATION_V2=1` to exercise natural conversation. Leave `LLM_ENABLED=0` for deterministic-only development, or provide `GROQ_API_KEY`, set `LLM_ENABLED=1`, and enable AI explicitly in the bot.

Start the local database and apply migrations:

```powershell
bash scripts/devdb.sh
.venv\Scripts\python.exe -m alembic check
```

Start the API in one terminal:

```powershell
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Start the Telegram worker in a second terminal:

```powershell
.venv\Scripts\python.exe -m api.worker
```

For a local debugging session, capture the already-redacted application logs in ignored artifact files:

```powershell
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log 2>&1 | Tee-Object -FilePath artifacts\api.log
.venv\Scripts\python.exe -m api.worker 2>&1 | Tee-Object -FilePath artifacts\worker.log
```

Run those commands in separate terminals. FitKit logs error codes and aggregate metrics, not Telegram messages, health payloads, tokens, or conversation contents.

Check the processes from another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

### Ngrok tunnel for Telegram

With the API and worker running, start ngrok in another terminal:

```powershell
ngrok config add-authtoken $env:NGROK_AUTHTOKEN
ngrok http 8000
```

Copy the HTTPS forwarding origin shown by ngrok, without a trailing slash, into `.env` as `PUBLIC_BASE_URL`. Restart the API and worker after changing `.env`. Register this webhook URL with Telegram:

```text
https://<your-ngrok-host>/integrations/telegram/webhook
```

Use the same `TELEGRAM_WEBHOOK_SECRET` value when registering Telegram's `secret_token`. Keep `TELEGRAM_BOT_TOKEN` in environment variables and out of pasted URLs, shell history, screenshots, and logs. If the ngrok hostname changes, update `PUBLIC_BASE_URL`, restart the processes, and register the new webhook URL.

### Local tests

The API tests require the dedicated database created by `scripts/devdb.sh`; the database name must end in `_test`.

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://postgres:fitkit@127.0.0.1:5432/fitkit_beta_test'
.venv\Scripts\python.exe -m pytest tests/test_engine tests/test_unit -q
.venv\Scripts\python.exe -m pytest tests/test_api -q
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe scripts/eval_groq.py --offline
.venv\Scripts\python.exe -m compileall -q api engine tests
.venv\Scripts\python.exe scripts/check_secrets.py
```

The tests apply migrations and truncate the dedicated test database. Never point `TEST_DATABASE_URL` at the local application or production database.

Useful commands:

With `TELEGRAM_CONVERSATION_V2=1`, common requests work naturally: “I did squat 3x5 at 100 kg”, “How am I doing?”, “It’s leg day—planning”, “What do you remember about me?”, or “Set my target for squat to 5 reps increment 2.5 kg”. Planning is grounded in confirmed goals and recent workout names; numeric recommendations still come only from deterministic services. Slash commands remain reliable shortcuts and recovery controls.

| Command | Purpose |
|---|---|
| `/start`, `/skip`, `/help` | Optional setup and help |
| `80 kg` | Preview a current weight measurement |
| `/log squat 3x5 at 100 kg rpe 7` | Preview a workout; date defaults visibly to the user's local day |
| `/target squat 5 reps increment 2.5 kg` | Set a progression target and optional equipment increment |
| `/recommend squat` | Check deterministic progression |
| `/correct <workout ID>` | Preview and edit a saved workout |
| `/profile`, `/goals`, `/today`, `/progress`, `/health` | View or update fitness details |
| `/preferences` | Timezone, units, and optional AI interpretation |
| `/connect-health`, `/dashboard` | Private health pairing and temporary dashboard |
| `/cancel`, `/delete` | Cancel a preview or begin confirmed deletion |

Start with [local development](docs/development.md). For hosting, read the [operations runbook](docs/operations.md). The [implementation and rollout plan](docs/private_beta.md) records the release gates and subsequent scope. The [schema guide](docs/data_schema.md) and [Shortcuts contract](docs/apple_shortcuts.md) document persistence and ingestion.

`LLM_ENABLED=1` makes AI available; each user must still explicitly enable it. Provider calls send only the current message and minimal setup context. Every interpreted mutation requires a preview. `LLM_ENABLED=0` disables the provider globally. The model never supplies progression rules or missing measurements.

Run `python -m pytest tests/ -q` against a dedicated PostgreSQL database ending in `_test`. Engine and unit tests can run separately without PostgreSQL. `python scripts/eval_groq.py --offline` checks deterministic routing and adversarial extraction boundaries without calling Groq.

The repository is prepared for private-beta validation. A real phone sync, live synthetic Groq benchmark, deployment credentials/certificates, and seven days of beta observation remain operational release gates. Full program generation, nutrition/hydration, nudges, voice, and a native iOS companion are later work.
