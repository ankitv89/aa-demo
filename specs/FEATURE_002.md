# FEATURE 002 — Usage, last 24 hours

**Status:** Draft  
**Date:** 2026-11-12  
**Owner:** Ankit  
**Depends on:** FEATURE 001

## 1. Purpose

Show how many notifications the engine handled in the rolling last 24 hours. A browser page reads one usage API and displays totals by channel, status, and calling service. Validation of that page is recorded in an evidence report that includes screenshots of the UI.

This screen is the usage UI left out of FEATURE 001. Sending, Kafka, and provider calls stay as specified there.

## 2. Goals

- One page, `GET /usage`, shows notification usage for the last 24 hours.
- Counts come from `notifications.created_at` in Postgres. The page does not call MSG91, FCM, or SES.
- The window is rolling: `created_at >= now() - 24 hours` at request time, in UTC.
- A reviewer can check the numbers against SQL, and the check is written down with screenshots.
- The evidence report file name is the feature name plus `_evidences`: `FEATURE_002_evidences.md`.

## 3. Out of scope

- Usage older than 24 hours, custom date ranges, and CSV export.
- Per-recipient or message-body browsing. The page shows counts, not notification content.
- Charts beyond the counts and breakdown tables.
- Authentication changes. The page and the usage API use the same `X-Api-Key` as FEATURE 001.
- Editing FEATURE 001 send behavior.

## 4. Design

### 4.1 API

`GET /v1/usage`

Header: `X-Api-Key: <key>`

Response `200`:

```json
{
  "window_start": "2026-11-11T10:31:00Z",
  "window_end": "2026-11-12T10:31:00Z",
  "total": 12,
  "by_channel": { "sms": 5, "push": 4, "email": 3 },
  "by_status": { "queued": 1, "sending": 0, "sent": 9, "failed": 2 },
  "by_source": { "orders": 10, "billing": 2 }
}
```

| Field | Rule |
| --- | --- |
| `window_end` | UTC time of the query |
| `window_start` | `window_end` minus 24 hours |
| `total` | Rows in `notifications` with `created_at` in `[window_start, window_end]` |
| `by_channel` | Counts for `sms`, `push`, and `email`. A channel with no rows is `0` |
| `by_status` | Counts for `queued`, `sending`, `sent`, and `failed`. A status with no rows is `0` |
| `by_source` | One key per distinct `source` in the window. Omitted when `total` is 0 |

Rows with `created_at` before `window_start` are excluded. `accepted` and `enqueue_failed` are not buckets on this page; they still count toward `total` when they fall inside the window.

Missing or unknown `X-Api-Key` returns `401`. The handler does not publish to Kafka and does not call a provider.

### 4.2 UI

`GET /usage` returns an HTML page. The browser sends the API key the operator entered on the page, then calls `GET /v1/usage`.

The page shows:

- Title: Usage, last 24 hours
- Window start and window end in UTC
- Total notifications
- A channel table: SMS, Push, Email, each with its count
- A status table: Queued, Sending, Sent, Failed, each with its count
- A source table: one row per calling service and its count
- A refresh control that calls `GET /v1/usage` again
- An empty state when `total` is 0: the tables show `0` and the text "No notifications in the last 24 hours"

The page does not list send ids, recipients, or message bodies.

### 4.3 Validation and evidence

Validation is a recorded check, not a code comment. After the page is running, the reviewer:

1. Notes `window_start` and `window_end` shown on the page.
2. Runs the SQL below against the same database.
3. Compares `total`, each channel count, each status count, and each source count with the page.
4. Saves screenshots of the UI into the evidence report.

```sql
SELECT channel, status, source, count(*)
FROM notifications
WHERE created_at >= now() - interval '24 hours'
  AND created_at <= now()
GROUP BY channel, status, source;
```

The evidence report path is `evidence/FEATURE_002_evidences.md`. The file name is the feature name `FEATURE_002` plus the suffix `_evidences`. The report embeds the screenshots so they are visible in the file. A path or filename that does not end with `FEATURE_002_evidences` does not meet this feature.

The report contains:

| Section | Content |
| --- | --- |
| Feature | `FEATURE_002` |
| Result | Pass or fail for each check |
| Window | `window_start` and `window_end` shown on the page |
| Comparison | Page count and SQL count for total, channel, status, and source |
| Screenshots | Populated page, and the empty state |
| Ran at | UTC timestamp |

Required screenshots, stored next to the report and embedded in it:

| File | Screen |
| --- | --- |
| `evidence/FEATURE_002_evidences_populated.png` | Page with at least one notification in the window, totals and all three tables visible |
| `evidence/FEATURE_002_evidences_empty.png` | Page when the last 24 hours contain no rows, including the empty-state text |

## 5. Feature list

| ID | Feature | Description | Priority |
| --- | --- | --- | --- |
| F2-01 | Usage API | `GET /v1/usage` returns total, channel, status, and source counts for the rolling last 24 hours. | Must |
| F2-02 | Rolling window | Counts include only rows with `created_at` in the 24 hours ending at request time. Older rows are excluded. | Must |
| F2-03 | Usage page | `GET /usage` shows the window, the total, and the channel, status, and source tables. | Must |
| F2-04 | Empty state | When the window has no rows, every count is `0` and the page shows "No notifications in the last 24 hours". | Must |
| F2-05 | Refresh | The refresh control loads `GET /v1/usage` again and replaces the numbers on the page. | Must |
| F2-06 | Access check | The usage API and the page's data request reject a missing or unknown API key with `401`. | Must |
| F2-07 | Count validation | A reviewer compares the page to SQL for the same window. Each displayed count matches the query. | Must |
| F2-08 | Screenshots in evidence | The populated screen and the empty screen are embedded in the evidence report. | Must |
| F2-09 | Evidence file name | The report file is `evidence/FEATURE_002_evidences.md`, the feature name plus `_evidences`. | Must |

## 6. Acceptance criteria

### F2-01 Usage API

- **AC-01.** Given notifications in the last 24 hours, when a caller with a valid API key gets `/v1/usage`, then the response is `200` and includes `window_start`, `window_end`, `total`, `by_channel`, `by_status`, and `by_source`.
- **AC-02.** Given that call, when the handler runs, then it does not publish to Kafka and does not call MSG91, FCM, or SES.

### F2-02 Rolling window

- **AC-03.** Given a notification created 23 hours ago and one created 25 hours ago, when the caller gets `/v1/usage`, then `total` includes only the newer row.
- **AC-04.** Given the response, when `window_end` and `window_start` are compared, then `window_end` is 24 hours after `window_start`.

### F2-03 Usage page

- **AC-05.** Given a valid API key and usage data, when the operator opens `/usage`, then the page shows the title "Usage, last 24 hours", the UTC window, the total, and rows for SMS, Push, Email, Queued, Sending, Sent, and Failed.
- **AC-06.** Given the page has loaded, when its numbers are compared to `GET /v1/usage`, then the total and each breakdown match the API.

### F2-04 Empty state

- **AC-07.** Given no notifications in the last 24 hours, when the operator opens `/usage`, then every count is `0` and the page shows "No notifications in the last 24 hours".

### F2-05 Refresh

- **AC-08.** Given the page is showing a total, when a new notification is accepted and the operator refreshes, then the total increases by one.

### F2-06 Access check

- **AC-09.** Given a missing or unknown `X-Api-Key`, when the caller gets `/v1/usage`, then the response is `401` and the body has no counts.

### F2-07 Count validation

- **AC-10.** Given the page is showing a non-zero window, when the reviewer runs the SQL in §4.3 for that same window, then `total`, every channel count, every status count, and every source count on the page equal the query.

### F2-08 Screenshots in evidence

- **AC-11.** Given validation has been run, when a reader opens the evidence report, then the populated usage page is visible as an image in the report.
- **AC-12.** Given the empty window has been opened, when a reader opens the evidence report, then the empty state, including "No notifications in the last 24 hours", is visible as an image in the report.

### F2-09 Evidence file name

- **AC-13.** Given validation is complete, when the evidence artifact is stored, then the report path is `evidence/FEATURE_002_evidences.md`.
- **AC-14.** Given that report, when its sections are read, then it records Pass or Fail per check, the window, the page-versus-SQL counts, and the UTC time of the run.

## 7. Requirements traceability matrix

| Req | Feature | Acceptance criteria | Test | Priority |
| --- | --- | --- | --- | --- |
| FR-01 | F2-01 Usage API | AC-01, AC-02 | TC-01 Get `/v1/usage` with data present. Assert the JSON fields. Assert no Kafka publish and no provider call | Must |
| FR-02 | F2-02 Rolling window | AC-03, AC-04 | TC-02 Insert one row at 23 hours and one at 25 hours. Assert only the newer row is counted and the window is 24 hours wide | Must |
| FR-03 | F2-03 Usage page | AC-05, AC-06 | TC-03 Open `/usage` and assert the title, window, and breakdown rows. Assert the DOM counts equal the API | Must |
| FR-04 | F2-04 Empty state | AC-07 | TC-04 Open `/usage` with no rows in the window. Assert zeroes and the empty-state text | Must |
| FR-05 | F2-05 Refresh | AC-08 | TC-05 Record the total, accept one notification, refresh, assert the total increased by one | Must |
| FR-06 | F2-06 Access check | AC-09 | TC-06 Get `/v1/usage` with no key and with an unknown key. Assert `401` | Must |
| FR-07 | F2-07 Count validation | AC-10 | TC-07 Run the §4.3 SQL and compare each count with the page. Record the comparison in the evidence report | Must |
| FR-08 | F2-08 Screenshots in evidence | AC-11, AC-12 | TC-08 Embed `FEATURE_002_evidences_populated.png` and `FEATURE_002_evidences_empty.png` in the report and confirm both render | Must |
| FR-09 | F2-09 Evidence file name | AC-13, AC-14 | TC-09 Assert the report path is `evidence/FEATURE_002_evidences.md` and that result, window, comparison, and timestamp sections are present | Must |
