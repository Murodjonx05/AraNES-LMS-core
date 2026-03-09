# AraNES-LMS-core Backend

FastAPI backend for an LMS-oriented API with:

- JWT Bearer authentication via `Authorization` header
- RBAC roles plus per-user permission overrides
- i18n storage for short and large translations
- SQLite persistence via async SQLAlchemy

## Tech Stack

- Python `3.11+`
- FastAPI
- SQLAlchemy async + `aiosqlite`
- Alembic
- Pydantic
- `authx`

## Project Structure

- `main.py` - local development entrypoint that runs `uvicorn`
- `src/app.py` - FastAPI app factory, middleware wiring, OpenAPI customization
- `src/api.py` - aggregate API router mounted under `/api`
- `src/config.py` - environment-driven application configuration
- `src/database.py` - session dependency and shared SQLAlchemy base
- `src/runtime.py` - runtime context for config, engine, security, session factory
- `src/startup/` - lifespan and bootstrap seeding
- `src/auth/` - signup, login, revoke, current-user flow
- `src/user_role/` - RBAC models, permissions, roles, users, bootstrap defaults
- `src/i18n/` - translation models, seed data, CRUD, API routes
- `src/utils/` - profiler, in-process HTTP helper, superuser utility
- `migrations/` - Alembic migration history
- `tests/` - unit and integration tests
- `docs/` - project notes and analysis
- `data/` - default local SQLite runtime data

## API Prefixes

All API routes are mounted under `/api`.

- Auth: `/api/v1/auth`
- RBAC: `/api/v1/rbac`
- i18n: `/api/v1/i18n`

## Main Endpoints

### Auth

- `POST /api/v1/auth/signup`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/reset`
- `GET /api/v1/auth/me`

Auth flow is header-only:

1. `POST /api/v1/auth/login` to receive an `access_token`
2. Send `Authorization: Bearer <access_token>`
3. Call protected endpoints such as `GET /api/v1/auth/me`
4. Call `POST /api/v1/auth/reset` with the current access token to revoke it and force a fresh login

### RBAC

- `GET /api/v1/rbac/roles`
- `GET /api/v1/rbac/roles/{role_id}`
- `POST /api/v1/rbac/roles`
- `PATCH /api/v1/rbac/roles/{role_id}`
- `DELETE /api/v1/rbac/roles/{role_id}`
- `PATCH /api/v1/rbac/roles/{role_id}/permissions`
- `POST /api/v1/rbac/roles/reset`
- `POST /api/v1/rbac/roles/role-registry/`
- `GET /api/v1/rbac/users`
- `GET /api/v1/rbac/users/{user_id}`
- `POST /api/v1/rbac/users`
- `PATCH /api/v1/rbac/users/{user_id}`
- `PUT /api/v1/rbac/users/{user_id}/password`
- `DELETE /api/v1/rbac/users/{user_id}`
- `PATCH /api/v1/rbac/users/{user_id}/permissions`
- `POST /api/v1/rbac/users/reset`

Read access to RBAC and i18n resources is permission-gated. Default `Admin` and `SuperAdmin`
roles can read them; lower roles cannot unless explicitly granted via role/user permissions or
plugin-provided permission registration.

### i18n

- `GET /api/v1/i18n/small`
- `GET /api/v1/i18n/small/{key}`
- `PUT /api/v1/i18n/small`
- `GET /api/v1/i18n/large`
- `GET /api/v1/i18n/large/{key1}/{key2}`
- `PUT /api/v1/i18n/large`

### System

- `GET /health`
- `GET /ready`

## Local Development

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements/dev.txt
```

### 3. Configure environment

Start from the example file:

```bash
cp .env.example .env
```

At minimum, set:

```bash
export JWT_SECRET_KEY="replace-with-a-real-secret"
```

There are two common runtime modes:

- Native app + Docker Redis:
  use `.env` with `REDIS_URL=redis://localhost:6379/0`
- Docker app + Docker Redis:
  Docker also reads `.env`, but `docker-compose.yml` overrides `REDIS_URL` to
  `redis://redis:6379/0` inside the container

If `DATABASE_URL` is unset, the app defaults to a local SQLite file at
`data/db.sqlite3`.

Optional overrides include `ENVIRONMENT`, `LOG_LEVEL`, `DATABASE_URL`, `HOST`,
`PORT`, and CORS settings.

Useful operational toggles:

```bash
export REQUEST_LOG_ENABLED="true"
export AUDIT_LOG_ENABLED="true"
export RATE_LIMIT_ENABLED="true"
export RATE_LIMIT_WINDOW_SECONDS="60"
export RATE_LIMIT_MAX_REQUESTS="20"
export REDIS_ENABLED="false"
export REDIS_URL="redis://localhost:6379/0"
export REDIS_DEFAULT_TTL_SECONDS="3600"
export REDIS_HEARTBEAT_ENABLED="true"
export REDIS_HEARTBEAT_SCHEDULE_SECONDS="60,600,1200,3600,14400,28800,43200"
```

### Docker Compose

Do not hardcode secrets in `docker-compose.yml`.

Use `.env` as the shared configuration source:

```bash
docker compose up --build
```

Compose always starts the bundled Redis alongside the app. The app waits for a
healthy Redis before startup and uses `redis://redis:6379/0` inside the Compose
network.

Compose reads `.env`, then overrides `REDIS_URL` for the containerized app:

- native app needs `redis://localhost:6379/0`
- Docker app needs `redis://redis:6379/0`

If you run the app natively and only Redis in Docker, keep using `.env` and set:

```bash
export REDIS_ENABLED="true"
export REDIS_URL="redis://localhost:6379/0"
```

To see which host port was assigned to the bundled Redis:

```bash
docker compose port redis 6379
```

### 4. Apply migrations

```bash
alembic upgrade head
```

### 5. Run the app

```bash
python main.py
```

Or:

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

For containerized production-style runs, the Docker image uses `gunicorn` with
`uvicorn.workers.UvicornWorker`. You can tune process settings through:

```bash
export WEB_CONCURRENCY="2"
export GUNICORN_TIMEOUT="60"
export GUNICORN_KEEPALIVE="5"
export GUNICORN_MAX_REQUESTS="1000"
export GUNICORN_MAX_REQUESTS_JITTER="100"
```

Container startup runs a one-time prestart bootstrap before Gunicorn:

1. `alembic upgrade head`
2. default role/i18n seed
3. optional superuser bootstrap from env

After that, Gunicorn workers start with `STARTUP_DB_BOOTSTRAP_ENABLED=false` in
Compose, so DB bootstrap does not run again inside each worker.

## Startup Behavior

On application startup, the service:

1. builds runtime context and cache services
2. checks Redis availability when enabled and starts the Redis heartbeat loop
3. seeds default roles and i18n translations
4. bootstraps the initial superuser when env bootstrap is enabled
5. if schema is missing, applies Alembic migrations and retries bootstrap once

This in-process DB bootstrap is kept enabled by default for native/dev runs.
Containerized Compose runs should prefer the dedicated prestart step instead.

## Current Constraints

- Python `3.11+` is required
- SQLite is the default local and development database
- profiler behavior is env-switchable via `APP_PROFILING_ENABLED`
- integration tests can be profiled, but profiler overhead still affects timing numbers
- rate limiting is Redis-backed when Redis bootstrap succeeds; bootstrap failure falls back to in-memory, while mid-request Redis limiter failure is denied with `429`
- Redis-backed caches are optional; if Redis is unavailable, the app continues in degraded mode and falls back to the database/in-memory paths

## Tooling

This repo keeps dependency installation in `requirements/*.txt`.

- `requirements/dev.txt` is the development install target
- `pyproject.toml` stores lightweight tooling metadata only
- no Poetry, Hatch, or Tox workflow is introduced in this repo

## Migration Layer

Alembic is the only migration path.

```bash
alembic upgrade head
```

```bash
alembic revision --autogenerate -m "describe change"
```

Alembic uses project metadata from `src.database.Model.metadata`, plus the auth
revocation table metadata, and imports model modules from `src/i18n/models.py`
and `src/user_role/models.py`.

## Default Data

Seeded roles:

- `SuperAdmin`
- `Admin`
- `User`
- `Guest`
- `Teacher`
- `Student`

Default signup role:

- `Student`

Required translation languages:

- `en`
- `ru`
- `uz`

## Performance Baseline

Performance numbers in this repository are intentionally treated as local snapshots, not fixed guarantees.

Use these commands to get a fresh baseline on the current machine:

- full suite: `./venv/bin/pytest -v --profile --profile-top=20`
- unit/integration split: `./venv/bin/pytest -q tests` and `./venv/bin/pytest -q tests/integration`

Current profiling guidance:

- compare runs only under the same profiling flags and machine conditions
- treat `setup` and `call` separately when reading slow integration tests
- use `logs/profile.log.json` as a rolling request-level trace, not as a canonical benchmark artifact

Repeatable wrapper:

```bash
./scripts/profile_tests.sh
```

Integration tests now run with app profiling enabled by default, so request/function samples are
written automatically into `logs/profile.log.json` unless you override the log directory.

Optional custom profile log directory:

```bash
TEST_PROFILE_LOG_DIR=./logs ./scripts/profile_tests.sh
```

Request profiling and function profiling can be controlled separately:

```bash
export APP_PROFILING_ENABLED=true
export APP_FUNCTION_PROFILING_ENABLED=false
```

Decorator override example:

```python
@profile_function(enabled=False)
async def cheap_helper():
    ...
```

## Operational Notes

- `GET /health` is a lightweight process health endpoint
- `GET /ready` verifies database readiness
- request logs are emitted through logger `aranes.request`
- admin-sensitive mutating actions are emitted through logger `aranes.audit`
- if Redis-backed rate-limiter bootstrap fails, the app falls back to an in-memory limiter
- if an already-Redis-backed limiter breaks during request evaluation, the current request is denied with `429`
- Redis-backed caches remain optional at the feature level; when Redis is unavailable, the service continues with degraded non-Redis paths
- cached i18n endpoints:
  - `GET /api/v1/i18n/small`
  - `GET /api/v1/i18n/small/{key}`
  - `GET /api/v1/i18n/large`
  - `GET /api/v1/i18n/large/{key1}/{key2}`
- cached RBAC endpoints:
  - `GET /api/v1/rbac/roles`
  - `GET /api/v1/rbac/roles/{role_id}`
  - `GET /api/v1/rbac/users`
  - `GET /api/v1/rbac/users/{user_id}`
- Redis miss or Redis outage falls back to DB reads
- auth token revocation source of truth is the database table `auth_revoked_token_jtis`
- Redis revocation entries are only a shared cache layer above the database
- i18n and RBAC writes invalidate only the corresponding Redis keys after successful DB commit

## Tests

Run all tests:

```bash
./venv/bin/pytest -q
```

Run with timing profile:

```bash
./venv/bin/pytest -v --profile --profile-top=20
```

Run integration tests only:

```bash
./venv/bin/pytest -q tests/integration
```

Run Ruff:

```bash
./venv/bin/ruff check .
```

## CI/CD

GitHub Actions workflows live in [`.github/workflows/ci.yml`](/run/media/aestra/data/PYTHON/lms/.github/workflows/ci.yml) and [`.github/workflows/cd.yml`](/run/media/aestra/data/PYTHON/lms/.github/workflows/cd.yml).

CI runs on push and pull request:

- install `requirements/dev.txt`
- run `ruff check .`
- run `pytest -q`
- build `Dockerfile.core`

CD publishes the container image to `GHCR`:

- trigger: push to `main`, version tags `v*`, or manual dispatch
- image: `ghcr.io/<owner>/<repo>`
- tags: branch/tag/SHA, plus `latest` on the default branch

## Related Docs

- [docs/release.md](/run/media/aestra/data/PYTHON/lms/docs/release.md)
- [docs/analysis_report_ru.md](/run/media/aestra/data/PYTHON/lms/docs/analysis_report_ru.md)

## Docker

`Dockerfile.core` installs runtime dependencies from `requirements/release.txt`.

Local multi-service startup:

```bash
docker compose up --build
```

This starts:

- `app`
- `redis`

The app keeps working from DB even if Redis is unavailable; Redis only accelerates i18n single-item reads when reachable.

## License

This project is licensed under `GPL-3.0-only`. See [LICENSE](/run/media/aestra/data/PYTHON/lms/LICENSE).
