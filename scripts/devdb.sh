#!/usr/bin/env bash
# Bring up the local FitKit PostgreSQL database and apply migrations.
#
# Usage:  bash scripts/devdb.sh
#
# Starts Docker Desktop if needed, ensures the fitkit-postgres container is
# running, creates the application and test databases, and migrates to head.
# It is idempotent: safe to re-run at any time.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="fitkit-postgres"
POSTGRES_PASSWORD="fitkit"
APP_DB="fitkit"
TEST_DB="fitkit_test"
# The base Alembic revision is stable; Alembic resolves HEAD dynamically.
BASE_REVISION="20260812_0001"

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  echo "No .venv found under $ROOT. Create it first (see docs/development.md)." >&2
  exit 1
fi

ensure_docker() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  echo "Docker engine is not running; starting Docker Desktop..."
  local exe="/c/Program Files/Docker/Docker/Docker Desktop.exe"
  if [ -f "$exe" ]; then
    cmd //c start "" "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"
  fi
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      echo "Docker is ready."
      return 0
    fi
    sleep 5
  done
  echo "Timed out waiting for Docker. Start Docker Desktop, then re-run this script." >&2
  return 1
}

ensure_container() {
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      echo "Starting container $CONTAINER..."
      docker start "$CONTAINER" >/dev/null
    fi
  else
    echo "Creating container $CONTAINER..."
    docker run -d --name "$CONTAINER" \
      -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
      -p 5432:5432 postgres:16 >/dev/null
  fi
}

wait_ready() {
  for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready." >&2
  return 1
}

ensure_db() {
  local name="$1"
  if docker exec "$CONTAINER" psql -U postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$name'" | grep -q 1; then
    return 0
  fi
  echo "Creating database $name..."
  docker exec "$CONTAINER" createdb -U postgres "$name"
}

migrate() {
  local db="$1"
  local has_version has_schema

  has_version="$(docker exec "$CONTAINER" psql -U postgres -d "$db" -tAc \
    "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='alembic_version'")"

  if [ -n "$has_version" ]; then
    echo "Applying migrations..."
    (cd "$ROOT" && "$PY" -m alembic upgrade head)
    return
  fi

  has_schema="$(docker exec "$CONTAINER" psql -U postgres -d "$db" -tAc \
    "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='user_profiles'")"
  if [ -n "$has_schema" ]; then
    echo "Legacy schema found; stamping base revision before migrating..."
    (cd "$ROOT" && "$PY" -m alembic stamp "$BASE_REVISION")
  fi

  echo "Applying migrations..."
  (cd "$ROOT" && "$PY" -m alembic upgrade head)
}

ensure_docker
ensure_container
wait_ready
ensure_db "$APP_DB"
ensure_db "$TEST_DB"
migrate "$APP_DB"

echo
echo "Database is ready. Start the backend with:"
echo "  python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload"
