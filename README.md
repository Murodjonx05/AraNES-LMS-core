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

At minimum, set:

```bash
export JWT_SECRET_KEY="replace-with-a-real-secret"
```

Optional overrides include `DATABASE_URL`, `HOST`, `PORT`, and CORS settings.

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

## Startup Behavior

On application startup, the service:

1. runs optional env-driven superuser bootstrap
2. seeds default roles
3. seeds default i18n translations

Schema migrations are not executed at runtime. Apply Alembic migrations before starting the app.

## Current Constraints

- Python `3.11+` is required
- SQLite is the default local and development database
- profiler behavior is env-switchable via `APP_PROFILING_ENABLED`
- integration tests disable profiler logging by default to avoid distorting endpoint timings
- auth-sensitive rate limiting is in-memory and intended as a local/single-process safeguard
- Redis cache is optional; if unavailable, i18n reads fall back to the database automatically

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

Alembic uses project metadata from `src.database.Model.metadata` and imports model modules from `src/i18n/models.py` and `src/user_role/models.py`.

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

Current local baseline after the latest test-fixture and endpoint cleanup:

- full suite: `./venv/bin/pytest -v --profile --profile-top=20`
- latest passing result: `71 passed in 1.27s`
- dominant remaining slow test: `tests/integration/test_auth_protection.py::test_me_requires_access_token`
- that remaining outlier is mostly `setup`, not endpoint `call` time

Endpoint-level local observations from `logs/profile.log.json`:

- `POST /api/v1/auth/login` is the heaviest normal product path
- `GET /api/v1/auth/me` is already in a healthy local range
- RBAC read endpoints are already in a healthy local range
- `GET /openapi.json` is a tooling/dev endpoint, not product traffic

These numbers are meaningful only when compared under similar local conditions, fixture setup, and profiling configuration.

Repeatable wrapper:

```bash
./scripts/profile_tests.sh
```

## Operational Notes

- `GET /health` is a lightweight process health endpoint
- `GET /ready` verifies database readiness
- request logs are emitted through logger `aranes.request`
- admin-sensitive mutating actions are emitted through logger `aranes.audit`
- current rate limiting is in-memory, so it is not a distributed production limiter
- Redis is used only for optional i18n single-item read-through caching in v1
- cached endpoints in v1:
  - `GET /api/v1/i18n/small/{key}`
  - `GET /api/v1/i18n/large/{key1}/{key2}`
- Redis miss or Redis outage falls back to DB reads
- i18n writes invalidate corresponding Redis keys after successful DB commit

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

## Related Docs

- [docs/release.md](/mnt/data/PYTHON/lms/docs/release.md)
- [docs/analysis_report_ru.md](/mnt/data/PYTHON/lms/docs/analysis_report_ru.md)

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

This project is licensed under `GPL-3.0-only`. See [LICENSE](/mnt/data/PYTHON/lms/LICENSE).
