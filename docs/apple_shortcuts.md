# Apple Shortcuts health bridge

The backend accepts a user-configured daily health snapshot. Telegram cannot read Health data itself. Verify the phone-side setup on a real device before inviting beta users; endpoint tests do not establish iOS permission or automation behavior.

Run `/connect-health` to obtain the endpoint and your private pairing token. Send it in `X-Health-Pairing-Token`, never in a URL or shared Shortcut. Running `/connect-health` again rotates the token.

## Validate without storing measurements

Configure a Shortcuts request with **POST**, JSON content type, and the pairing header. Use `https://YOUR_HOST/ingest/shortcut/validate` with synthetic values:

```json
{"hrv":60,"resting_hr":55,"sleep_hours":7}
```

The response includes `valid: 3` and `inserted: 0`. This tests pairing and validation without saving fake readings. Do not send synthetic values to the normal endpoint for a real user.

## Store a real snapshot

Build a dictionary from measurements you permit Shortcuts to read. Send it to `https://YOUR_HOST/ingest/shortcut`:

```json
{
  "batch_id": "snapshot-2026-09-08-0700",
  "measured_at": "2026-09-08T07:00:00-04:00",
  "hrv": 58.2,
  "resting_hr": 54,
  "sleep_hours": 6.8
}
```

This example documents the shape; use actual readings and capture time. HRV is milliseconds, resting heart rate is beats/minute, and sleep is hours asleep. At least one metric is required. Omit missing metrics instead of inserting zero. Supplied timestamps must include a timezone and cannot be in the future.

Keep the same batch ID and dictionary for retries of one capture. A new capture needs a new ID. IDs allow up to 100 letters, numbers, `.`, `_`, `:`, or `-`. `measured_at` may be omitted only with a stable batch ID; the server then records first receipt time. Prefer capture time for offline uploads. The flat format has one snapshot time and cannot preserve separate timestamps for each metric.

Responses report `inserted`, `duplicates`, `skipped`, `skipped_reasons`, and `batch_duplicate`. An identical batch inserts nothing on retry. Reusing an ID with different content returns 409. Independent metric uniqueness protects `(user, metric, timestamp, source)`.

Supply one verified daily sleep total. Exclude awake and in-bed-only intervals, and avoid overlapping devices/categories. If the Shortcut cannot establish a total, omit sleep. Different sleep totals within a local day, or multiple sources for a metric/day, are reported as conflicting and excluded from recovery decisions. Use one bridge per daily metric.

Set `/preferences timezone <IANA timezone>` to the snapshot calendar. After a real upload, check `/health` for values, source, timestamp, stale status and conflicts. Missing health data still permits workout logging and progression from training history.

## Device acceptance check

Before enabling recurring automation, compare one authorized upload with the phone: values, units, timezone, source and skipped counts. Repeat the exact request and confirm no duplicate. Rotate the pairing token and confirm the old one is rejected. Record the iOS version and actual available Shortcuts actions in the beta review.

Personal automation labels and permissions vary by device/version. Keep a manual run available and treat the bridge as best-effort daily synchronization. A native HealthKit companion remains future scope.

## Troubleshooting

- **401:** missing, incorrect or revoked token; rotate it and update the header.
- **409:** changed content reused an ID; retain original requests for retries and use new IDs for new captures.
- **422:** invalid range, empty dictionary, missing timestamp/batch ID, or a naive/future timestamp.
- **Duplicates:** expected for repeated captures; existing metrics are not overwritten.
- **Conflicts:** verify daily sources and sleep totals against the phone.

The legacy `/ingest/health` adapter accepts grouped Health Auto Export payloads with the same per-user pairing header. Optional `X-Ingest-Batch-Id` has the same reuse rule. Declared unsupported units are skipped. Legacy timestamps without an offset retain their historical UTC interpretation; prefer explicit offsets. Shared API-key compatibility remains disabled in production.
