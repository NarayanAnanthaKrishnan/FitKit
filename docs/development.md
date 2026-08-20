# Local development

## Configure the environment

1. Copy `.env.example` to `.env`.
2. Fill in local-only values for `DATABASE_URL`, `FITKIT_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_WEBHOOK_SECRET`.
3. Use a separate development Telegram bot. A Telegram bot has one active webhook, so never point the production bot at a laptop.
4. If a token or webhook secret is exposed, rotate it immediately through BotFather and replace the local value.

`.env` is ignored by Git. The repository only contains placeholders.

## Create the virtual environment

Run these commands manually from the repository root:

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
# source .venv/bin/activate    # Linux/macOS

python -m pip install --upgrade pip
python -m pip install -c constraints.txt -e ".[dev]"
```

For Windows Command Prompt, activate the environment with:

```text
.venv\\Scripts\\activate.bat
```

## Start PostgreSQL and migrate

Run the idempotent dev-database script. It starts Docker Desktop if needed, ensures the `fitkit-postgres` container is running, creates the `fitkit` and `fitkit_test` databases, and applies migrations:

```bash
bash scripts/devdb.sh
```

For a pre-existing local database that predates Alembic (tables present but no `alembic_version`), the script stamps the base revision first and then migrates. The manual equivalent is:

```bash
docker run -d --name fitkit-postgres \
  -e POSTGRES_PASSWORD=fitkit \
  -p 5432:5432 postgres:16

until docker exec fitkit-postgres pg_isready -U postgres; do sleep 1; done
docker exec fitkit-postgres createdb -U postgres fitkit
docker exec fitkit-postgres createdb -U postgres fitkit_test
python -m alembic upgrade head
```

Schema changes are explicit. The API does not run `create_all()` or raw `ALTER TABLE` statements on startup. For a pre-existing local database, make a backup and run `python scripts/bootstrap_legacy_db.py --apply`. The command is an explicit operator action: it creates missing current-model tables, applies only the known onboarding nullability changes, validates required columns, and stamps Alembic head. It refuses to run when an Alembic version already exists.

## Alembic and Mako files

Alembic owns versioned database schema changes. Keep `alembic.ini`, `alembic/env.py`, `alembic/versions/*.py`, and `alembic/script.py.mako` in source control. `alembic.ini` configures the tool, `env.py` supplies the database URL and model metadata, and each revision records an upgrade/downgrade. The `.mako` file is a template used only when Alembic generates a new revision. Mako is a normal installed dependency, not an application source directory. Generated `__pycache__` files and anything under `.venv/` are ignored and should not be committed.

## Run the API and tests

Run the backend directly from the active virtual environment. Structured REST requests must include the API key and `X-Telegram-User-Id` for an already-linked Telegram account; the server resolves that external identity to an internal user ID:

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API liveness check is `GET http://localhost:8000/health`. Stop the backend with `Ctrl+C`. Run tests from another terminal after activating `.venv` there as well:

```bash
python -m pytest tests/ -v
```

API tests use the separate `fitkit_test` database and do not share application data.

## Test Telegram locally

Use Cloudflare Tunnel or ngrok to expose the local API over HTTPS, then register the development bot webhook with:

```text
https://<tunnel-host>/integrations/telegram/webhook
```

Send the configured secret in Telegram's webhook registration request as `secret_token`; the backend validates it on every update. Check the bot's webhook status through the Telegram Bot API after registration. When the tunnel URL changes, register the new URL and verify `/health` before testing `/start`.

Do not log webhook URLs containing bot tokens, full Telegram updates, health payloads, or conversation contents.

## CI checks

CI installs the project, creates an isolated PostgreSQL test database, checks tracked files for common credential patterns, compiles Python sources, validates the initial migration, and runs the full test suite. Normal CI does not call Telegram or a model provider.

## Staging / deploy

A minimal staging stack is provided as `docker-compose.yml` (PostgreSQL + API). Provide secrets through a `.env` file next to it or the shell environment, then run:

```bash
docker compose up --build
```

Required environment variables: `FITKIT_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and `PUBLIC_BASE_URL` (the public HTTPS origin used to build `/connect-health` and `/dashboard` links). The container applies Alembic migrations on start before serving the API on port 8000. This is a staging foundation, not a full production deployment: still add a TLS terminator, secret management, and database backups before production use.
