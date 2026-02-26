# AraNES-LMS-core Backend (FastAPI)

A lightweight FastAPI backend for an LMS-oriented API with:

- JWT Bearer authentication (`authx`) via `Authorization` header
- RBAC roles/user permission overrides
- i18n key/value storage for short and large translations
- SQLite persistence via SQLAlchemy async

## Tech Stack

- Python 3.11+
- FastAPI
- SQLAlchemy (async) + `aiosqlite`
- Pydantic
- `authx` (JWT auth)

## Project Structure

- `main.py` - local dev entrypoint (`uvicorn.run`)
- `src/app.py` - FastAPI app wiring (middleware + routes + lifespan)
- `src/api/router.py` - aggregate API router mounted under `/api`
- `src/db/` - DB base/session helpers (canonical imports)
- `src/startup/` - startup lifecycle orchestration and bootstrap seeding (no runtime schema migrations)
- `src/config/` - app config and security wiring
- `src/auth/` - signup/login/reset/me endpoints
- `src/user_role/` - RBAC models, permission logic, role/user endpoints
- `src/i18n/` - translation models, registry, seeding, endpoints
- `data/` - SQLite database (runtime data)
- `docs/` - project notes

## API Prefixes

All routes are mounted under `/api`.

- Auth: `/api/v1/auth`
- RBAC: `/api/v1/rbac`
- i18n: `/api/v1/i18n`

## Main Endpoints (current)

### Auth

- `POST /api/v1/auth/signup`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/reset`
- `GET /api/v1/auth/me`

Auth flow is header-only:

1. `POST /api/v1/auth/login` (JSON body) to receive `access_token`
2. Click Swagger `Authorize` and paste the access token as Bearer token
3. Call protected endpoints (for example `GET /api/v1/auth/me`)
4. If you want to force re-login, call `POST /api/v1/auth/reset` with the current `Authorization: Bearer <access_token>`. It revokes that access token, and you must login again to get a new one.

Swagger UI note: the global `Authorize` button may keep a previously entered token. If a protected endpoint appears to work "without a token", re-check in a fresh tab/incognito or verify with `curl`.

### RBAC

- `GET /api/v1/rbac/roles`
- `GET /api/v1/rbac/roles/{role_id}`
- `POST /api/v1/rbac/roles`
- `PATCH /api/v1/rbac/roles/{role_id}`
- `DELETE /api/v1/rbac/roles/{role_id}`
- `PATCH /api/v1/rbac/roles/{role_id}/permissions`
- `POST /api/v1/rbac/roles/reset`
- `POST /api/v1/rbac/roles/role-registry/` (protected)
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

## Local Development

### 1. Create/activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

Install development dependencies:

```bash
pip install -r requirements/dev.txt
```

### 3. Apply migrations

```bash
alembic upgrade head
```

### 4. Run the app

```bash
python main.py
```

Or:

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

## Startup Behavior

On app startup, the project:

1. runs optional non-interactive superuser bootstrap (env-driven)
2. seeds default roles and i18n translations

Schema creation/migrations are not performed at runtime. Use Alembic (`alembic upgrade head`) before starting the app.

This flow is organized under `src/startup/` (`bootstrap.py`, `lifespan.py`).

Interactive superuser creation is available via `scripts/create_superuser.py` and is not part of app startup.

## Local Runtime Artifacts (intentional)

This refactor does not delete or relocate local runtime artifacts such as `venv/`, `data/`, `__pycache__/`, or local logs. They may exist in the working directory for local development convenience.

## Migration Layer Status

Alembic is the primary and only migration path (`alembic.ini`, `migrations/`).

### Alembic Commands

```bash
alembic upgrade head
```

```bash
alembic revision --autogenerate -m "describe change"
```

Alembic autogenerate uses project metadata from `src.db.base.Model.metadata` and imports model modules from `src/i18n/models.py` and `src/user_role/models.py`.

## Configuration (current)

Environment variables currently used:

- `HOST` (default `0.0.0.0`)
- `PORT` (default `8000`)

Other settings (DB path, CORS, auth header/JWT config, required languages) are assembled in `src/config/app.py` (with a mix of env-driven values and code defaults).

## Default Data / Roles

Default roles are seeded:

- `SuperAdmin`
- `Admin`
- `User`
- `Guest`
- `Teacher`
- `Student`

Default signup role is `Student`.

Required translation languages:

- `en`
- `ru`
- `uz`

## Docker

`Dockerfile.core` installs runtime dependencies from `requirements/release.txt`.

## Tests

Run all tests:

```bash
venv/bin/pytest -q
```

Run integration tests only (ASGI in-process, isolated SQLite DB):

```bash
venv/bin/pytest -q tests/integration
```

## Known Gaps / Production Notes

- `JWT_SECRET_KEY` is required; provide it via env/`.env` in every environment.
- Auth uses Bearer tokens in the `Authorization` header (Swagger `Authorize` is the recommended local testing flow). `POST /api/v1/auth/reset` revokes the currently authenticated access token and forces a new login to obtain another token.
- Token revocation persists in the shared database (`auth_revoked_token_jtis`) and is created via Alembic migrations.
- Integration tests now cover auth/header enforcement and protected RBAC/i18n write endpoints, but additional edge-case coverage is still useful.

## License

This project is licensed under the GNU General Public License v3.0 only (`GPL-3.0-only`).

- Internal/private use (without distribution): source disclosure is not required.
- If you distribute the software (modified or unmodified), you must provide source code under GPLv3, including your changes.

See `LICENSE` for the full license text.
