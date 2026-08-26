# Apple Shortcuts bridge — copy-ready recipe

This is FitKit's first-party Apple Health bridge. It requires **no third-party
exporter** and **no iOS app built by FitKit**:

```text
Apple Health on iPhone
    -> Apple Shortcuts
    -> HTTPS POST /ingest/shortcut
    -> FitKit health_metrics
    -> Telegram /health, /today, and recommendations
```

Apple does not provide a server-side Apple Health API. The Shortcut must run on
the iPhone because that is where the user grants Health permissions.

## Before building it

1. Deploy FitKit behind HTTPS. Do not use a localhost URL from the iPhone.
2. In Telegram, send `/connect-health`.
3. Copy the displayed **Shortcuts endpoint** and pairing token. The token is a
   write credential; do not put it in a shared screenshot, public Shortcut, or
   URL. Send `/connect-health` again if the token must be rotated.
4. In the iPhone Health app, confirm that Shortcuts is allowed to read:
   - Heart Rate Variability
   - Resting Heart Rate
   - Sleep

The API contract is:

```http
POST https://YOUR_HOST/ingest/shortcut
Content-Type: application/json
X-Health-Pairing-Token: YOUR_PRIVATE_TOKEN
```

```json
{
  "measured_at": "2026-08-20T07:00:00Z",
  "hrv": 58.2,
  "resting_hr": 54,
  "sleep_hours": 6.8
}
```

All health fields are optional. The Shortcut should omit a field when it could
not read that metric. FitKit stores the values under the user who owns the
pairing token; it never trusts a user ID sent by the Shortcut.

## Shortcut 1: smoke test

Create this first. It verifies the URL and token without reading any Health
data.

Create a new Shortcut named **FitKit — Smoke Test** and add these actions:

### 1. Text

Paste this exact JSON into a **Text** action:

```json
{"hrv":60,"resting_hr":55,"sleep_hours":7,"measured_at":"2026-08-20T00:00:00Z"}
```

Use a timestamp that you will not accidentally reuse for real data. The
endpoint treats the same metric, timestamp, source, and user as one record, so
running this smoke test twice is safe.

### 2. Get Contents of URL

Configure the action as follows:

- **URL:** the Shortcuts endpoint printed by `/connect-health`
- **Method:** `POST`
- **Headers:**
  - `Content-Type` = `application/json`
  - `X-Health-Pairing-Token` = your private pairing token
- **Request Body:** `JSON`
- Set the JSON body to the output of the Text action.

If your iOS version shows a body type selector, choose **JSON**, not Form or
File. If it asks for a dictionary, use **Get Dictionary from Input** between
the Text and Get Contents of URL actions.

### 3. Show Result

Add **Show Result** after Get Contents of URL and run the Shortcut. A successful
response resembles:

```json
{"inserted":3,"skipped":0,"skipped_reasons":[]}
```

Then send `/health` to the FitKit bot. The smoke-test values should appear.
Delete this test Shortcut after verification, or keep it only on your private
device.

## Shortcut 2: daily health sync

Create a new Shortcut named **FitKit — Daily Health Sync**. Put the endpoint and
token in the first two Text actions so they are easy to update, but remember
that the token must remain private.

### Configuration actions

1. **Text** — paste the Shortcuts endpoint, for example:
   `https://fitkit.example.com/ingest/shortcut`
2. **Set Variable** — name it `FitKit Endpoint`.
3. **Text** — paste the pairing token from `/connect-health`.
4. **Set Variable** — name it `FitKit Token`.

### Stable daily timestamp

Use a stable timestamp for the daily snapshot so repeatedly running the
Shortcut on the same day does not create duplicate rows:

5. **Current Date**.
6. **Get Start of Day** from Current Date.
7. **Format Date** with date format `Custom` and this format string:
   `yyyy-MM-dd'T'HH:mm:ssXXXXX`
8. **Set Variable** — name it `Snapshot Time`.
9. **Dictionary** with one key:
   - `measured_at` = `Snapshot Time`

If your iOS version uses a different label for Get Start of Day, use the Date
action that returns midnight at the start of the current local day. The API
normalizes timezone offsets to UTC.

### Read HRV

10. Add **Find Health Samples**:
    - **Type:** Heart Rate Variability
    - **Start Date:** Start of Day
    - **End Date:** Current Date
    - **Sort by:** End Date, Latest First
    - **Limit:** 1
11. Add **Count** to the result.
12. Add **If** Count is greater than `0`.
13. Inside the If block:
    - **Get Item from List** — First Item
    - **Get Details of Health Sample** — `Value`
    - **Set Dictionary Value** — key `hrv`, value the sample Value
14. Close the If block.

### Read resting heart rate

15. Add **Find Health Samples**:
    - **Type:** Resting Heart Rate
    - **Start Date:** Start of Day
    - **End Date:** Current Date
    - **Sort by:** End Date, Latest First
    - **Limit:** 1
16. Repeat the Count / If / First Item / Get Details steps above.
17. Inside the If block, use **Set Dictionary Value** with key
    `resting_hr`.
18. Close the If block.

### Read sleep duration

Sleep is represented as one or more Health samples on some iOS versions. Do
not use the text value of a sleep category as `sleep_hours`; sum the durations
of the samples instead.

19. Add **Find Health Samples**:
    - **Type:** Sleep Analysis (it may appear as Sleep)
    - **Start Date:** Yesterday
    - **End Date:** Current Date
    - **Sort by:** Start Date, Oldest First
    - **Limit:** 100
20. If the action exposes a **Value** filter, select only samples whose value
    is an asleep state, such as Asleep, Core, Deep, REM, or Awake as appropriate
    for the Health data you want. Do not include In Bed unless you intentionally
    want time in bed rather than sleep time.
21. Add **Set Variable** with name `Sleep Total` and value `0`.
22. Add **Repeat with Each** item in the sleep-sample list.
23. Inside the repeat block:
    - **Get Details of Health Sample** from Repeat Item — `Start Date`.
    - **Set Variable** — name `Sleep Start`.
    - **Get Details of Health Sample** from Repeat Item — `End Date`.
    - **Get Time Between Dates** from Sleep Start to the sample End Date,
      in hours.
    - **Calculate** `Sleep Total + calculation result`.
    - **Set Variable** — name `Sleep Total`.
24. Close the repeat block.
25. Add **If** Sleep Total is greater than `0`.
26. Inside the If block, **Set Dictionary Value** with key `sleep_hours` and
    value `Sleep Total`, rounded to one decimal place if the action is
    available.
27. Close the If block.

If your iOS version exposes a direct numeric sleep-duration value instead of
sleep category samples, use that value for `sleep_hours` and skip the duration
sum. If Sleep Analysis is not available in Shortcuts, the Shortcut still works:
it will send HRV and resting HR and simply omit sleep.

### Send the dictionary

28. Add **Get Contents of URL**:
    - **URL:** the `FitKit Endpoint` variable
    - **Method:** `POST`
    - **Headers:**
      - `Content-Type` = `application/json`
      - `X-Health-Pairing-Token` = the `FitKit Token` variable
    - **Request Body:** `JSON`
    - JSON input: the Dictionary built above
29. During setup, add **Show Result** after the request. Remove it after the
    Shortcut is verified if you do not want a response displayed.

A successful daily run normally returns:

```json
{"inserted":3,"skipped":0,"skipped_reasons":[]}
```

It may return `inserted: 1` or `inserted: 2` when Health has no recent sample
for one or more metrics. That is expected; missing data is not fabricated.

## Run it every morning

1. In Shortcuts, open **Automation** and choose `+` → **Create Personal
   Automation**.
2. Choose **Time of Day** or the **Waking Up** sleep trigger.
3. Add **Run Shortcut** and select **FitKit — Daily Health Sync**.
4. Turn off **Ask Before Running** if iOS offers that option.
5. Run the Shortcut manually once after creating the automation and check
   `/health` in Telegram.

Personal automations are not guaranteed to run while the phone is powered off,
restricted, or unable to access Health. For production expectations, treat this
as a daily best-effort sync rather than an always-on stream.

## Share the Shortcut safely

After building and testing it on your own iPhone:

1. Open the Shortcut's details menu.
2. Choose **Share** → **Copy iCloud Link**.
3. Share the link or publish a QR code for users.
4. In the shared copy, users must replace the endpoint and pairing token with
   their own values before running it.

Never publish a Shortcut containing your own pairing token. A shared Shortcut
is a recipe, not a shared account connection; every user must run
`/connect-health` and use their own token.

## Troubleshooting

- **401 Unauthorized:** the token is wrong, revoked, truncated, or being sent
  under the wrong header. Rotate it with `/connect-health` and update the
  Shortcut's token Text action.
- **Cannot connect:** verify the URL is the public HTTPS endpoint and does not
  include a trailing path other than `/ingest/shortcut`. Check the TLS
  certificate and reverse-proxy routing.
- **`inserted: 0` on a repeated daily run:** expected when the same day's
  snapshot already exists. Use a new date only for a deliberate test.
- **HRV/resting HR missing:** check Health app permissions and the Find Health
  Samples date range. The latest sample must fall between Start of Day and the
  time the Shortcut runs.
- **Sleep is wrong or missing:** inspect which Sleep Analysis values your iOS
  version exposes. Sum asleep intervals only; do not treat In Bed as asleep.
- **No automatic run:** iOS may require the phone to be unlocked or may pause a
  personal automation. Run the Shortcut manually as a fallback.

The `/ingest/shortcut` endpoint accepts only the three supported metrics,
normalizes timestamps, scopes writes to the pairing owner, and uses an
idempotent database constraint. It does not log the pairing token or raw health
payload.
