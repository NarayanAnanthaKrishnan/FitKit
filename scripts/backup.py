"""Encrypt a PostgreSQL custom dump or restore it into a NEW drill database.

Uses DATABASE_URL and a separately stored FITKIT_BACKUP_KEY (Fernet).
No credentials are passed in subprocess arguments or printed. Needs PostgreSQL
client tools locally, or --container with a running PostgreSQL container.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid
from urllib.parse import unquote, urlsplit

from cryptography.fernet import Fernet


def pg_command(tool, args, *, container=None, input=None):
    url = urlsplit(os.environ["DATABASE_URL"])
    env = dict(os.environ)
    env.update(PGHOST="127.0.0.1" if container else (url.hostname or "127.0.0.1"),
               PGPORT="5432" if container else str(url.port or 5432),
               PGUSER=unquote(url.username or "postgres"), PGPASSWORD=unquote(url.password or ""))
    command = [tool, *args]
    if container:
        command = ["docker", "exec", "-i", "-e", "PGHOST", "-e", "PGPORT", "-e", "PGUSER", "-e", "PGPASSWORD", container, *command]
    result = subprocess.run(command, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=600)
    if result.returncode:
        raise RuntimeError(f"{tool} failed")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create", "restore-drill"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--container")
    args = parser.parse_args()
    try:
        key = os.environ["FITKIT_BACKUP_KEY"]
        if key == os.getenv("FITKIT_QUEUE_KEY"):
            raise ValueError("Backup and queue keys must be separate")
        cipher = Fernet(key.encode())
        source = unquote(urlsplit(os.environ["DATABASE_URL"]).path.lstrip("/"))
        if not source:
            raise ValueError("DATABASE_URL must name a database")
        if args.command == "create":
            if args.file.exists():
                raise FileExistsError("Backup already exists")
            dump = pg_command("pg_dump", ["--format=custom", "--no-owner", "--no-acl", "--dbname", source], container=args.container)
            encrypted = cipher.encrypt(dump)
            # Exclusive creation protects previous backups, including a race.
            with args.file.open("xb") as output:
                output.write(encrypted)
            print(json.dumps({"status": "encrypted", "bytes": len(encrypted)}))
        else:
            dump = cipher.decrypt(args.file.read_bytes())
            target = "fitkit_restore_" + uuid.uuid4().hex[:16]
            pg_command("createdb", [target], container=args.container)
            pg_command("pg_restore", ["--exit-on-error", "--no-owner", "--no-acl", "--dbname", target], container=args.container, input=dump)
            query = "SELECT version_num FROM alembic_version; SELECT count(*) FROM exercise_taxonomy; SELECT count(*) FROM user_profiles; SELECT count(*) FROM workout_sessions;"
            checks = pg_command("psql", ["--no-psqlrc", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--dbname", target, "--command", query], container=args.container).decode().splitlines()
            print(json.dumps({"status": "restored", "database": target, "schema": checks[0], "taxonomy": int(checks[1]), "users": int(checks[2]), "workouts": int(checks[3])}))
    except Exception as exc:
        parser.exit(1, f"Backup operation failed ({type(exc).__name__}). No existing database was overwritten.\n")


if __name__ == "__main__":
    main()
