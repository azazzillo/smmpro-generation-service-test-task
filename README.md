# Generation Service

An asynchronous generation service built with FastAPI and PostgreSQL. It accepts generation requests, charges user tokens, dispatches tasks to fake providers, retries eligible failures, and refunds tokens when generation fails.

The service is designed to handle concurrent requests and duplicate webhooks without double-charging or double-refunding users.

## Features

- **Token accounting** — every balance change is recorded in the ledger.
- **Provider fallback** — retries the next eligible provider after technical failures or synchronous request errors.
- **Failure handling** — payload errors terminate a task; moderation failures skip providers configured with `skip_on_moderation`.
- **Idempotent webhooks** — duplicate payment and provider callbacks do not apply the same financial operation twice.
- **Watchdog** — detects provider attempts that exceed `PROVIDER_TIMEOUT` and moves tasks forward.
- **Concurrency safety** — database-level coordination protects balance updates and the active-task limit.
- **Persistent state** — task and attempt state is stored in PostgreSQL, not in process memory.
- **Database migrations** — schema changes are managed with Alembic.
- **Multiple workers** — the API runs with four Uvicorn workers.

## Tech stack

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy with async support
- Alembic
- Docker Compose
- Pytest, HTTPX and asyncpg

## Requirements

- Docker Desktop with Docker Compose, or Docker Engine with the Compose plugin
- Python 3.11+ for running tests locally

## Getting started

### 1. Clone the repository

```bash
git clone <REPOSITORY_URL>
cd gen-service
```

Replace `<REPOSITORY_URL>` with the repository URL.

### 2. Start the services

```bash
docker compose up -d --build
```

Docker Compose starts PostgreSQL, the migration service, the API and both fake providers (`alpha` and `beta`). The migration service applies the database migrations before the API starts.

The default host ports used by this setup are:

| Service | Host address |
|---|---|
| API | `http://localhost:8001` |
| PostgreSQL | `localhost:5433` |
| Provider alpha | `localhost:9001` |
| Provider beta | `localhost:9002` |

The API listens on port `8000` inside its container and is published on host port `8001`.

### 3. Check the service

```bash
curl http://localhost:8001/health
```

Expected response:

```json
{
  "ok": true
}
```

Check container status and logs if a service fails to start:

```bash
docker compose ps
docker compose logs -f app
docker compose logs migrate
```

## Configuration

The application and fake providers are configured through environment variables in `docker-compose.yml`.

| Variable | Purpose |
|---|---|
| `DB_URL` | PostgreSQL connection string used inside Docker |
| `WEBHOOK_SECRET` | Shared secret used to sign and verify webhooks |
| `PROVIDER_TIMEOUT` | Maximum time to wait for a provider attempt |
| `WATCHDOG_INTERVAL` | Interval between watchdog checks |
| `PROVIDER_URLS` | URLs of the fake providers |
| `SELF_URL` | Internal URL used by the application |
| `DELAY_MIN` | Minimum fake-provider response delay |
| `DELAY_MAX` | Maximum fake-provider response delay |

The Compose configuration uses internal Docker hostnames for communication between containers. For example, the application connects to PostgreSQL at `db:5432`, not `localhost:5433`.

For tests, the provider timeout and delay can be shortened:

```bash
PROVIDER_TIMEOUT=3 DELAY_MIN=1 DELAY_MAX=2 \
docker compose up -d --build
```

These values are intended for testing, not production use.

## API

### `POST /generate`

Creates a generation task, charges the model price and dispatches the task to the first eligible provider.

Example request:

```json
{
  "user_id": 1,
  "model_slug": "image-fast",
  "prompt": "A mountain landscape at sunrise",
  "ref_images": []
}
```

The user must exist and have enough tokens. The model must support the supplied number of reference images.

Relevant responses:

- `402 Payment Required` — insufficient token balance.
- `429 Too Many Requests` — the user has reached the active-task limit.
- `400 Bad Request` — no provider leg supports the supplied reference-image count.

On success, the response contains the created `task_id`.

### `POST /webhooks/providers/{name}`

Receives a provider result. The fake providers send either a successful completion with a result URL or a failure with an error type.

Supported failure types:

- `technical` — try the next eligible provider.
- `moderation` — skip subsequent legs marked `skip_on_moderation`.
- `payload` — fail the task without retrying.

Provider webhooks are authenticated using the `X-Signature` header. The signature is an HMAC-SHA256 digest of the **raw request body**, calculated with `WEBHOOK_SECRET`.

### `POST /webhooks/payments`

Receives payment notifications containing `payment_id`, `user_id`, `tokens` and `status`.

Repeated notifications for the same payment must not credit the user's balance more than once.

### `GET /tasks/{id}`

Returns the task status, current provider leg and attempt history, including provider names, failure types and timestamps.

### `GET /users/{id}/balance`

Returns the user's current balance and recent ledger entries.

## Model catalog

The initial catalog is defined through database migrations.

| Model | Price | Provider chain |
|---|---:|---|
| `image-fast` | 2 tokens | `alpha` (up to 4 reference images) → `beta` (up to 10) |
| `video-long` | 25 tokens | `beta` (up to 2 reference images) → `alpha` (up to 1, skipped after moderation failure) |

A provider leg is eligible only when its reference-image limit is satisfied.

## Financial consistency and idempotency

The database is the source of truth for task state, balances and the ledger.

### Concurrent requests

Before charging a user, the service coordinates access to the user's database row and performs a conditional balance update. This prevents concurrent generation requests from spending more tokens than the user owns. The active-task limit is also checked while coordinating requests for that user.

### Exactly-once financial effects

Balance changes and their corresponding ledger entries are persisted together. Database transactions and state checks prevent repeated callbacks from applying the same charge, payment credit or refund more than once.

A refund is applied only once when a task reaches a terminal failure state. Duplicate or concurrent failure callbacks cannot issue additional refunds.

### Provider timeouts and late results

The watchdog detects attempts that exceed `PROVIDER_TIMEOUT` and advances the task according to the same retry rules used for provider failures.

If a provider sends `completed` after the task has already failed and its tokens have been refunded, the late result must not turn the task into a successful one. The terminal task state is preserved, preventing a task from being both refunded and completed.

### Process failures

Financial state transitions are stored in PostgreSQL rather than process-local memory. Database transactions ensure that a webhook's database changes are committed together or rolled back together if processing fails before the commit.

After a committed operation, a repeated webhook can be handled idempotently. A process failure around an outgoing HTTP request is a separate concern from webhook transaction handling; recovery of a task interrupted between committing its state and dispatching the request depends on the dispatch and watchdog implementation.

## Database migrations

Alembic manages the database schema. The Compose migration service applies migrations automatically during startup.

To apply migrations explicitly:

```bash
docker compose run --rm migrate
```

To create a new migration after changing the database models:

```bash
docker compose exec app \
  alembic revision --autogenerate -m "describe the change"
```

Review the generated migration before applying it. Then run:

```bash
docker compose run --rm migrate
```

## Running tests

The tests run locally against the API and PostgreSQL started by Docker Compose.

### 1. Start the application with test settings

```bash
PROVIDER_TIMEOUT=3 DELAY_MIN=1 DELAY_MAX=2 \
docker compose up -d --build
```

### 2. Create and activate a virtual environment

Linux / WSL:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the project dependencies:

```bash
pip install -r requirements.txt
```

### 3. Run the test suite

```bash
TEST_BASE_URL=http://localhost:8001 \
pytest -v tests/
```

The tests use PostgreSQL at `localhost:5433` by default. To override the test database connection, set `TEST_DATABASE_URL`.

**Important:** the test fixtures truncate several application tables and reset their identities before each test. Run the tests only against the dedicated test database, not a database containing data you need to preserve.

The test suite covers:

- duplicate payment webhooks;
- provider fallback after a failed attempt;
- refunds after generation failure;
- late completion after a refund;
- the invariant that each user's balance equals the sum of their ledger entries.

## Stopping the services

```bash
docker compose down
```

This stops and removes the Compose containers and network. It does not request deletion of named volumes.

## Scope

This is a test implementation. It uses fake providers and does not require a UI, user registration, real file storage or real payment processing. Generation results are represented by URLs rather than stored files.
