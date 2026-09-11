# Private-beta operations

## Provision and start

Keep the database private. Supply a dedicated bot token, webhook secret, random database password, `PUBLIC_BASE_URL` HTTPS origin, separate `FITKIT_QUEUE_KEY` and `FITKIT_MEMORY_KEY` Fernet keys, and an explicit comma-separated `FITKIT_BETA_USER_IDS` invitation list. Set `FITKIT_PRODUCTION=1` and `ALLOW_LEGACY_INGEST_AUTH=0`. AI remains off until the operator enables it and each user consents.

Generate a Fernet key using this command in a private terminal, then store it in the secret manager or local untracked `.env`:

```text
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generate a different `FITKIT_BACKUP_KEY` and keep it outside the application environment, separately from backup files. Do not paste generated keys into issues, logs, or this repository. Queue key rotation requires draining jobs first; keep the old key until all jobs using it have completed or expired. Memory-key rotation requires an explicit re-encryption migration while the old key remains available; replacing it directly makes confirmed preference memory unreadable. Restore requires the backup key plus the queue and memory keys used by retained data.

Compose builds one image, runs `migrate` to completion, and then starts `app` and `worker`. The database has no published port. The application binds only `127.0.0.1:8000` on the host.

```text
docker compose up --build -d db migrate app worker
docker compose exec app python -m api.operator metrics
```

Use your existing TLS ingress or the optional Nginx profile. Set `FITKIT_TLS_DIR` to a directory containing `fullchain.pem` and `privkey.pem`, then run `docker compose --profile tls up -d proxy`. Configure certificate renewal outside the container and reload Nginx after renewal. The supplied proxy exposes only webhook, paired ingestion, validation, and dashboard routes; it disables URL logging and limits request bodies and rate.

Register the dedicated bot's webhook at `PUBLIC_BASE_URL/integrations/telegram/webhook` with its configured secret using your private operator tooling. Do not put the bot-token URL in shell history or monitoring output. Confirm a valid private-chat receipt and response, a rejected invalid secret, and an ignored non-invited account before adding users.

## Monitoring and failures

`/health` checks the HTTP process. `/ready` requires database access, migration head, taxonomy, and a worker heartbeat within 90 seconds. These endpoints are host/internal checks; the supplied public proxy does not expose them.

`python -m api.operator metrics` prints aggregate inbound/outbound status counts, oldest pending age, action outcomes/types (including validation rejection, provider fallback, and duplicate ingest batches), today's content-free conversation route/outcome/rating totals, routine-review task outcomes/stages, LLM p50/p95 latency, active feedback count, and today's global AI attempts. No chat content, tokens, health values, or user identifiers are included. Investigate any terminal failure, an oldest pending age over 120 seconds, or readiness failure. Review these signals daily during beta; alert routing must be configured by the host operator.

Inbound and outbound jobs use 60-second leases and per-user ordering. Domain writes and resulting delivery jobs commit together. On a crash before commit, the next worker retries the inbound job after its lease expires. On a crash after commit, its processed marker prevents a repeated write. Delivery uses bounded retries, honors Telegram `parameters.retry_after`, and becomes terminal after four failed claims. Encrypted payloads expire after 24 hours, including failed jobs. Successful jobs clear payloads immediately.

Telegram offers no application-supplied idempotency key for `sendMessage`: a response can be repeated if a worker crashes after Telegram accepts it but before the delivery marker commits. Workout and weight writes remain idempotent. An already in-flight external request cannot be recalled by deletion or AI opt-out; future queued work is cancelled or consent checked before processing.

For an investigated terminal job with retained payload, use `python -m api.operator retry inbound <update_id>` or `retry outbound <job_uuid>`. Identify the job locally using metadata-only database inspection; never dump encrypted payloads or action inputs into tickets. The command refuses active, expired, or completed jobs. Outbound replay may duplicate a delivered response.

## Backup and restore drill

The backup utility uses PostgreSQL client tools or an existing PostgreSQL container. Export `DATABASE_URL` and the separate `FITKIT_BACKUP_KEY` privately before running it. It never prints credentials or passes database passwords as command arguments. For this small beta, dump encryption happens in memory; schedule one backup at a time with enough memory for the dump and ciphertext.

```text
python scripts/backup.py create artifacts/fitkit-backup.fernet --container fitkit-db-1
python scripts/backup.py restore-drill artifacts/fitkit-backup.fernet --container fitkit-db-1
```

Creation refuses to overwrite a backup. Restore authenticates/decrypts it and always creates a new `fitkit_restore_<random>` database, runs `pg_restore --exit-on-error`, and reports migration/taxonomy/user/workout counts. It never replaces the source database. Compare counts with the source and run application read checks against the restored copy. Record restore duration. Drill databases remain available for inspection; remove the explicitly named drill database once review is complete.

Before each deployment, retain an encrypted backup and the prior image digest. Use host-managed encrypted storage and restrict backup access. Proposed beta policy: daily backups, seven daily copies, and one verified restore before inviting users. Implement retention in the host scheduler; this repository does not provision cloud storage or an external scheduler. Account deletion removes live application data; backups age out under that policy. Never restore deleted accounts into service without replaying deletion records under an operator-reviewed recovery procedure.

## Rollback

Stop ingress and workers before changing schema. Prefer rolling back the image only when its schema is compatible. Revision `20260908_0010` permits missing session energy; its downgrade refuses to fabricate values for workouts that omit energy. Revision `20260908_0011` adds short-lived encrypted conversation turns. Revision `20260910_0012` adds expiring conversation state, content-free interaction events, and encrypted 30-day feedback samples. Revision `20260910_0013` adds explicitly confirmed encrypted preference memory. Revision `20260911_0014` adds deterministic turn ordering and content-free task telemetry. Downgrading these revisions discards their conversation data. A data-bearing rollback to older releases therefore requires an operator-reviewed data migration or restoring the pre-upgrade backup into a fresh database and explicitly switching the application connection. Verify `/ready` and isolation before restoring ingress.

Keep application/proxy access logs free of query strings: dashboard URLs contain bearer tokens. The supplied image disables Uvicorn access logs; middleware strips query strings if logging is enabled locally. HTTPX logging is disabled in API and worker paths. Do not enable SQL echo or provider wire logging.
