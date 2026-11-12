# FEATURE 001 — Notification Engine

**Status:** Draft  
**Date:** 2026-11-12  
**Owner:** Ankit

## 1. Purpose

Provide one HTTP API that other services call to send a notification. The API accepts the request, assigns a send id, stores it, and places it on Kafka. A consumer reads the queue and delivers through the channel named in the request:

| Channel | Provider |
| --- | --- |
| SMS | MSG91 |
| Push | Google Firebase Cloud Messaging (FCM HTTP v1) |
| Email | Amazon SES |

Every provider call is stored with its send id and the provider’s API response.

## 2. Goals

- One ingest endpoint for SMS, push, and email.
- Callers receive a send id immediately. Delivery happens asynchronously.
- A Kafka consumer selects MSG91, FCM, or SES from the requested channel.
- Postgres stores the request, delivery status, send id, and provider response.
- The API, worker, Kafka, and Postgres run as containers via Docker Compose.

## 3. Out of scope

- User notification preferences, opt-out, and quiet hours.
- Templates managed inside this service. Callers send the provider-ready content (MSG91 template id and variables, FCM title/body/data, SES subject and body).
- Batch sends. One request delivers to one recipient.
- Scheduled or delayed send.
- Inbound webhooks from MSG91, FCM, or SES (delivery receipts, bounces, opens).
- Multi-region, horizontal autoscaling policy, and a production Kubernetes deploy.
- A user-facing UI.

## 4. Tech stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.12 |
| HTTP API | FastAPI |
| Queue | Apache Kafka (KRaft, single broker for local) |
| Database | PostgreSQL 16 |
| SMS | MSG91 Flow API v5 |
| Push | Firebase Cloud Messaging HTTP v1 |
| Email | Amazon SES API v2 `SendEmail` |
| Packaging | One application image; API and worker are two containers with different commands |
| Local infra | Docker Compose |

## 5. Design

### 5.1 Components

```text
Calling service
      │  POST /v1/notifications
      ▼
 notification-api          Postgres
      │  insert + publish     ▲
      ▼                       │ status + response logs
    Kafka  notifications.send │
      │                       │
      ▼                       │
 notification-worker ─────────┘
      │
      ├── sms   → MSG91
      ├── push  → FCM
      └── email → SES
```

| Component | Responsibility |
| --- | --- |
| `notification-api` | Authenticate the caller, validate the body, create the send id, persist the row, publish `{ "send_id": "..." }` to Kafka, return `202`. |
| `notification-worker` | Consume `notifications.send`, load the row, call the provider for `channel`, write the provider response, update status. |
| Postgres | System of record for the request, status, and provider response log. |
| Kafka | Buffer between accept and send. The API does not call MSG91, FCM, or SES. |

Producer and consumer use the same application image.

- API command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Worker command: `python -m app.worker`

### 5.2 Send lifecycle

| Status | Meaning |
| --- | --- |
| `accepted` | Row inserted. Publish to Kafka has not succeeded yet. |
| `queued` | Message is on `notifications.send`. |
| `sending` | Worker has taken the message and is calling the provider. |
| `sent` | Provider returned success. `provider_message_id` is stored. |
| `failed` | Provider rejected the request, or retries were exhausted. |
| `enqueue_failed` | Postgres insert succeeded and Kafka publish failed. |

Allowed moves:

`accepted` → `queued` | `enqueue_failed`  
`queued` → `sending`  
`sending` → `sent` | `queued` (retry) | `failed`

### 5.3 Kafka

| Topic | Contents |
| --- | --- |
| `notifications.send` | `{ "send_id": "<uuid>" }` |
| `notifications.send.dlq` | Same payload plus `error` and `attempts`, after retries are exhausted |

- Consumer group: `notification-worker`
- Delivery intent: at least once. The send id is the idempotency key on the provider side of the worker: a row already `sent` is acknowledged and not sent again.
- Publish failure after insert leaves the row `enqueue_failed`. A startup sweep republishes rows stuck in `accepted` or `enqueue_failed` for more than 30 seconds.

### 5.4 Channel routing

The worker reads `notifications.channel` and calls one adapter.

| `channel` | Adapter | Success signal stored as `provider_message_id` |
| --- | --- | --- |
| `sms` | MSG91 Flow API v5 | MSG91 request id |
| `push` | FCM HTTP v1 `messages:send` | FCM message resource name |
| `email` | SES v2 `SendEmail` | SES `MessageId` |

Provider credentials come from environment variables. They are never written to Postgres or logs.

| Variable | Used by |
| --- | --- |
| `MSG91_AUTH_KEY` | SMS |
| `MSG91_SENDER_ID` | SMS, default sender when the request omits one |
| `FIREBASE_PROJECT_ID` | Push |
| `FIREBASE_CREDENTIALS_JSON` | Push, service account used to mint the FCM access token |
| `AWS_REGION` | Email |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Email |
| `SES_FROM_ADDRESS` | Email, default From when the request omits one |

### 5.5 Persistence

`notifications`

| Column | Notes |
| --- | --- |
| `send_id` | UUID, primary key, generated by the API |
| `idempotency_key` | Unique per API client. Nullable when the caller does not send one |
| `source` | Calling service name |
| `channel` | `sms`, `push`, or `email` |
| `recipient` | Mobile, device token, or email address |
| `request_payload` | JSON body stored for replay and audit |
| `status` | Lifecycle value from §5.2 |
| `provider_message_id` | Id returned by MSG91, FCM, or SES |
| `attempt_count` | Provider calls made |
| `reference_id` | Optional caller reference, echoed back |
| `created_at`, `updated_at` | Timestamps |

`delivery_attempts`

| Column | Notes |
| --- | --- |
| `id` | Bigserial |
| `send_id` | FK to `notifications` |
| `attempt` | 1-based |
| `provider` | `msg91`, `fcm`, or `ses` |
| `request_snapshot` | JSON sent to the provider. Auth keys and tokens removed |
| `response_status` | HTTP status, or SES/FCM error code when there is no HTTP status |
| `response_body` | Provider response body, truncated at 16 KB |
| `provider_message_id` | Present on success |
| `latency_ms` | Time from provider request start to response |
| `error` | Exception or transport error when no response body exists |
| `created_at` | Timestamp |

One row is inserted for every provider call, including failed attempts.

### 5.6 Retries

| Provider result | Worker action |
| --- | --- |
| Success | Mark `sent`, commit offset |
| HTTP 4xx, or a permanent provider error (invalid token, unverified SES identity, MSG91 template error) | Mark `failed`, commit offset. No retry |
| Timeout, connection error, HTTP 429, HTTP 5xx | Increment `attempt_count`, set status back to `queued`, retry up to 3 attempts with backoff 5s, 30s, 120s |
| Still failing after 3 attempts | Mark `failed`, publish to `notifications.send.dlq`, commit offset |

### 5.7 Caller contract

`POST /v1/notifications`

Header: `X-Api-Key: <key>`  
Optional header: `Idempotency-Key`

```json
{
  "channel": "sms",
  "source": "orders",
  "reference_id": "order-1001",
  "sms": {
    "to": "+919876543210",
    "template_id": "template-id",
    "sender_id": "SENDER",
    "variables": { "otp": "123456" }
  }
}
```

Push body uses `push` instead of `sms`:

```json
{
  "channel": "push",
  "source": "orders",
  "push": {
    "token": "<fcm device token>",
    "title": "Order shipped",
    "body": "Your order is on the way",
    "data": { "order_id": "1001" }
  }
}
```

Email body uses `email`:

```json
{
  "channel": "email",
  "source": "orders",
  "email": {
    "to": "user@example.com",
    "subject": "Order shipped",
    "text": "Your order is on the way",
    "html": "<p>Your order is on the way</p>",
    "from": "noreply@example.com"
  }
}
```

`202 Accepted`

```json
{
  "send_id": "6f1c0c3e-2b4a-4e0a-9c1d-0a9a1b2c3d4e",
  "status": "queued",
  "channel": "sms"
}
```

`GET /v1/notifications/{send_id}` returns the row plus the latest delivery attempt (status, provider message id, response status, response body).

Validation:

| Channel | Required fields |
| --- | --- |
| `sms` | `sms.to` in E.164, `sms.template_id`. `sms.variables` is an object. `sms.sender_id` optional |
| `push` | `push.token`, `push.title`, `push.body`. `push.data` is a string map, optional |
| `email` | `email.to`, `email.subject`, and at least one of `email.text` or `email.html`. `email.from` optional |

The channel object must match `channel`. A body with `channel: "sms"` and an `email` object is `422`.

## 6. Feature list

| ID | Feature | Description | Priority |
| --- | --- | --- | --- |
| F-01 | Ingest API | `POST /v1/notifications` accepts a notification from another service and returns `202` with a send id. The API does not call MSG91, FCM, or SES. | Must |
| F-02 | Caller authentication | Requests without a configured `X-Api-Key` are rejected with `401`. The key identifies `source` when it is mapped to a service name. | Must |
| F-03 | Channel validation | The API rejects unknown channels and bodies that do not match the SMS, push, or email field rules, with `422` and field errors. | Must |
| F-04 | Send id | Every accepted request gets a new UUID send id. The id is returned to the caller and stored on the notification and on every delivery attempt. | Must |
| F-05 | Persist request | The API writes the notification row before it publishes to Kafka. | Must |
| F-06 | Queue on Kafka | A successful insert is followed by a publish of `{ "send_id" }` to `notifications.send`. The row moves to `queued`. Publish failure sets `enqueue_failed`. | Must |
| F-07 | Worker consume | The worker consumes `notifications.send`, loads the row by send id, and sets `sending` before the provider call. | Must |
| F-08 | Channel dispatch | The worker calls MSG91 when `channel` is `sms`, FCM when `channel` is `push`, and SES when `channel` is `email`. | Must |
| F-09 | SMS via MSG91 | The SMS adapter calls MSG91 Flow API v5 with auth key, template id, mobile, sender id, and variables. | Must |
| F-10 | Push via Firebase | The push adapter calls FCM HTTP v1 `messages:send` with the device token, notification title, body, and data. | Must |
| F-11 | Email via SES | The email adapter calls SES v2 `SendEmail` with from, to, subject, and text and/or html. | Must |
| F-12 | Response log | Each provider attempt inserts a `delivery_attempts` row containing send id, provider, request snapshot, response status, response body, provider message id, latency, and error. | Must |
| F-13 | Status update | Provider success sets `sent` and stores `provider_message_id`. Permanent failure or exhausted retries set `failed`. | Must |
| F-14 | Status read API | `GET /v1/notifications/{send_id}` returns status, channel, recipient, provider message id, and the latest provider response. Unknown send ids return `404`. | Must |
| F-15 | Idempotency | A repeated `Idempotency-Key` for the same API client returns the original send id and does not publish a second message. | Must |
| F-16 | Retry and DLQ | Transient provider failures retry up to 3 times. The last failure is logged. The message is then marked `failed` and copied to `notifications.send.dlq`. | Must |
| F-17 | Duplicate consume guard | If the worker sees a row already `sent`, it does not call the provider again. | Must |
| F-18 | Enqueue recovery | On startup the worker republishes rows left in `accepted` or `enqueue_failed`. | Should |
| F-19 | Secret redaction | Provider auth keys, AWS secret keys, and FCM access tokens are removed from `request_snapshot` and application logs. | Must |
| F-20 | Local runtime | `docker compose up` starts Postgres, Kafka, the API, and the worker. The API is reachable on port 8000. | Must |

## 7. Acceptance criteria

### F-01 Ingest API

- **AC-01.** Given a valid SMS, push, or email body and a valid API key, when the caller posts to `/v1/notifications`, then the response is `202` and the body contains `send_id`, `status: "queued"`, and `channel`.
- **AC-02.** Given a valid request, when the API responds, then no outbound call to MSG91, FCM, or SES has been made by the API process.

### F-02 Caller authentication

- **AC-03.** Given a missing or unknown `X-Api-Key`, when the caller posts a valid body, then the response is `401` and no row is inserted.
- **AC-04.** Given a valid API key, when the request is stored, then `notifications.source` is the request `source`.

### F-03 Channel validation

- **AC-05.** Given `channel` other than `sms`, `push`, or `email`, when the caller posts, then the response is `422` and no row is inserted.
- **AC-06.** Given `channel: "sms"` without `sms.to` or `sms.template_id`, when the caller posts, then the response is `422` and names the missing fields.
- **AC-07.** Given `channel: "push"` without `push.token`, `push.title`, or `push.body`, when the caller posts, then the response is `422`.
- **AC-08.** Given `channel: "email"` without `email.to`, `email.subject`, or both `email.text` and `email.html`, when the caller posts, then the response is `422`.
- **AC-09.** Given `channel: "sms"` and a populated `email` object instead of `sms`, when the caller posts, then the response is `422`.

### F-04 Send id

- **AC-10.** Given two valid requests, when both are accepted, then their `send_id` values differ.
- **AC-11.** Given an accepted request, when the worker finishes a provider call, then `delivery_attempts.send_id` equals the `send_id` returned to the caller.

### F-05 Persist request

- **AC-12.** Given a valid request, when the API returns `202`, then a `notifications` row exists for that send id with `channel`, `recipient`, and `request_payload`.
- **AC-13.** Given a Postgres outage, when the caller posts, then the response is `503` and nothing is published to Kafka.

### F-06 Queue on Kafka

- **AC-14.** Given a successful insert, when the API returns `202`, then `notifications.send` contains a message whose value is `{ "send_id": "<that id>" }` and the row status is `queued`.
- **AC-15.** Given Kafka is unavailable after the insert, when publish fails, then the row status is `enqueue_failed` and the response is `503` with the send id.

### F-07 Worker consume

- **AC-16.** Given a message on `notifications.send`, when the worker handles it, then it loads the notification by `send_id` and sets status to `sending` before the provider call.
- **AC-17.** Given a message whose send id does not exist, when the worker handles it, then it does not call a provider and it commits the offset.

### F-08 Channel dispatch

- **AC-18.** Given a queued SMS request, when the worker runs, then only the MSG91 adapter is invoked.
- **AC-19.** Given a queued push request, when the worker runs, then only the FCM adapter is invoked.
- **AC-20.** Given a queued email request, when the worker runs, then only the SES adapter is invoked.

### F-09 SMS via MSG91

- **AC-21.** Given a queued SMS, when MSG91 returns success, then the adapter sent template id, E.164 mobile, sender id, and variables, and `provider_message_id` is the MSG91 request id.
- **AC-22.** Given MSG91 returns a template or auth error, when the worker finishes, then status is `failed` and the MSG91 response body is stored on the attempt.

### F-10 Push via Firebase

- **AC-23.** Given a queued push, when FCM returns success, then the adapter sent token, title, body, and data, and `provider_message_id` is the FCM message name.
- **AC-24.** Given FCM returns an invalid-token error, when the worker finishes, then status is `failed` and the FCM error body is stored on the attempt.

### F-11 Email via SES

- **AC-25.** Given a queued email, when SES returns success, then the adapter sent from, to, subject, and the provided text or html, and `provider_message_id` is the SES `MessageId`.
- **AC-26.** Given SES rejects the identity or the address, when the worker finishes, then status is `failed` and the SES error is stored on the attempt.
- **AC-27.** Given the request omits `email.from`, when the adapter sends, then `SES_FROM_ADDRESS` is used.

### F-12 Response log

- **AC-28.** Given any provider call that returns a response, when the attempt is saved, then the row has `send_id`, `provider`, `response_status`, `response_body`, and `latency_ms`.
- **AC-29.** Given a provider timeout with no HTTP response, when the attempt is saved, then `error` is populated and `response_body` is null.
- **AC-30.** Given three attempts, when all are finished, then three `delivery_attempts` rows exist for that send id.

### F-13 Status update

- **AC-31.** Given a successful provider response, when the worker commits, then `notifications.status` is `sent` and `provider_message_id` is set.
- **AC-32.** Given a permanent provider error, when the worker commits, then `notifications.status` is `failed` and `attempt_count` is 1.

### F-14 Status read API

- **AC-33.** Given a send id, when the caller gets `/v1/notifications/{send_id}` with a valid API key, then the body includes `send_id`, `status`, `channel`, `recipient`, `provider_message_id`, and the latest attempt’s `response_status` and `response_body`.
- **AC-34.** Given an unknown send id, when the caller gets it, then the response is `404`.
- **AC-35.** Given a missing API key, when the caller gets a send id, then the response is `401`.

### F-15 Idempotency

- **AC-36.** Given a completed post with `Idempotency-Key`, when the same client repeats the same key, then the response is `200` with the original `send_id` and no second Kafka message is produced.
- **AC-37.** Given the same `Idempotency-Key` and a different body, when the client repeats it, then the response is `409`.
- **AC-38.** Given no `Idempotency-Key`, when the client posts the same body twice, then two send ids are created.

### F-16 Retry and DLQ

- **AC-39.** Given MSG91, FCM, or SES returns HTTP 503, when the worker handles it, then it retries until success or 3 attempts, and each attempt is logged.
- **AC-40.** Given 3 transient failures, when the last attempt is saved, then status is `failed` and `notifications.send.dlq` contains that send id.
- **AC-41.** Given HTTP 400 from the provider, when the worker handles it, then it does not retry and status is `failed`.

### F-17 Duplicate consume guard

- **AC-42.** Given a notification already `sent`, when a second Kafka message with the same send id is consumed, then the provider is not called and the offset is committed.

### F-18 Enqueue recovery

- **AC-43.** Given a row in `enqueue_failed` older than 30 seconds, when the worker starts, then it republishes that send id and sets status to `queued`.

### F-19 Secret redaction

- **AC-44.** Given a provider call, when `request_snapshot` and application logs are written, then `MSG91_AUTH_KEY`, AWS secret access key, and the FCM bearer token are absent.

### F-20 Local runtime

- **AC-45.** Given a clean checkout and the env file, when `docker compose up --build` finishes, then Postgres, Kafka, `notification-api`, and `notification-worker` are running and `GET /health` on port 8000 returns `200`.
- **AC-46.** Given the stack is up, when a caller posts a valid notification, then the row reaches `sent` or `failed` without a process started outside Compose.

## 8. Requirements traceability matrix

| Req | Feature | Acceptance criteria | Test | Priority |
| --- | --- | --- | --- | --- |
| FR-01 | F-01 Ingest API | AC-01, AC-02 | TC-01 Post each channel and assert `202`, send id, and zero provider calls from the API | Must |
| FR-02 | F-02 Caller authentication | AC-03, AC-04 | TC-02 Post without a key and with an unknown key; assert `401` and no row. Post with a valid key and assert `source` | Must |
| FR-03 | F-03 Channel validation | AC-05, AC-06, AC-07, AC-08, AC-09 | TC-03 Parametrized invalid bodies for unknown channel, missing SMS fields, missing push fields, missing email content, and mismatched channel object | Must |
| FR-04 | F-04 Send id | AC-10, AC-11 | TC-04 Accept two requests; assert distinct ids. After the worker runs, assert the attempt row uses the returned id | Must |
| FR-05 | F-05 Persist request | AC-12, AC-13 | TC-05 Assert the row after `202`. Stop Postgres and assert `503` with no Kafka message | Must |
| FR-06 | F-06 Queue on Kafka | AC-14, AC-15 | TC-06 Consume `notifications.send` and match `send_id`. Stop Kafka and assert `enqueue_failed` | Must |
| FR-07 | F-07 Worker consume | AC-16, AC-17 | TC-07 Assert status becomes `sending` before the provider stub is called. Publish an unknown send id and assert no provider call | Must |
| FR-08 | F-08 Channel dispatch | AC-18, AC-19, AC-20 | TC-08 Three queued rows; assert only MSG91, only FCM, and only SES are called respectively | Must |
| FR-09 | F-09 SMS via MSG91 | AC-21, AC-22 | TC-09 Stub MSG91 success and capture template id, mobile, sender, variables. Stub a template error and assert `failed` plus stored body | Must |
| FR-10 | F-10 Push via Firebase | AC-23, AC-24 | TC-10 Stub FCM success and capture token, title, body, data. Stub invalid token and assert `failed` plus stored error | Must |
| FR-11 | F-11 Email via SES | AC-25, AC-26, AC-27 | TC-11 Stub SES success and capture from, to, subject, body. Stub a rejected identity. Omit `from` and assert `SES_FROM_ADDRESS` | Must |
| FR-12 | F-12 Response log | AC-28, AC-29, AC-30 | TC-12 Assert attempt columns on success. Simulate a timeout and assert `error`. Force 3 attempts and count rows | Must |
| FR-13 | F-13 Status update | AC-31, AC-32 | TC-13 Success path asserts `sent` and provider message id. Permanent error asserts `failed` and `attempt_count = 1` | Must |
| FR-14 | F-14 Status read API | AC-33, AC-34, AC-35 | TC-14 GET a known id, an unknown id, and a GET without an API key | Must |
| FR-15 | F-15 Idempotency | AC-36, AC-37, AC-38 | TC-15 Replay the same key; change the body; post twice without a key | Must |
| FR-16 | F-16 Retry and DLQ | AC-39, AC-40, AC-41 | TC-16 Stub 503 then success. Stub 503 three times and read the DLQ. Stub 400 and assert a single attempt | Must |
| FR-17 | F-17 Duplicate consume guard | AC-42 | TC-17 Mark a row `sent`, redeliver the Kafka message, assert the provider stub was not called | Must |
| FR-18 | F-18 Enqueue recovery | AC-43 | TC-18 Insert an old `enqueue_failed` row, start the worker, assert a new Kafka message and status `queued` | Should |
| FR-19 | F-19 Secret redaction | AC-44 | TC-19 Run one attempt per provider and assert secrets are absent from `request_snapshot` and log output | Must |
| FR-20 | F-20 Local runtime | AC-45, AC-46 | TC-20 `docker compose up --build`, GET `/health`, post one notification per channel against stub or sandbox credentials | Must |

## 9. Local runtime

`docker-compose.yml` services:

| Service | Image / build | Port on the host |
| --- | --- | --- |
| `postgres` | `postgres:16` | `5432` |
| `kafka` | Apache Kafka KRaft | `9092` |
| `notification-api` | Application image | `8000` |
| `notification-worker` | Application image, worker command | none |

The API and worker wait until Postgres and Kafka accept connections. Schema is applied on API startup.

`GET /health` returns `200` when the API process is up. It does not call MSG91, FCM, or SES.

## 10. Open decisions

These do not block the feature list. Pick them at implementation time and record the choice here.

| Topic | Default for this spec |
| --- | --- |
| API framework | FastAPI |
| Kafka client | `confluent-kafka` |
| DB access | SQLAlchemy 2 and psycopg |
| Idempotency storage | Unique `(source, idempotency_key)` on `notifications`, with a hash of the request body for the `409` check |
| MSG91 mobile format | Digits only, country code included, as MSG91 expects (the API still requires E.164 on input and strips `+`) |
