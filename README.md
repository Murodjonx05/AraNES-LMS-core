# AraNES-LMS-core Backend (FastAPI)

A lightweight FastAPI backend for an LMS-oriented API with:

- cookie-based JWT authentication (`authx`)
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
- `src/app.py` - FastAPI app + CORS + router registration
- `src/database.py` - DB engine/session/lifespan setup + seeding
- `src/auth/` - signup/login/logout/protected endpoints
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
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/protected`

### RBAC

- `GET /api/v1/rbac/roles`
- `PATCH /api/v1/rbac/roles/{role_id}/permissions`
- `POST /api/v1/rbac/roles/reset`
- `GET /api/v1/rbac/users`
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

`requirements/release.txt` is currently not usable (it contains only `t`), so use `requirements/dev.txt` for now:

```bash
pip install -r requirements/dev.txt
```

### 3. Run the app

```bash
python main.py
```

Or:

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

## Startup Behavior

On app startup, the project:

1. creates DB tables
2. applies a small SQLite compatibility migration for `roles.title_key`
3. prompts to create a superuser if none exists
4. seeds default roles and i18n translations

Note: the superuser creation step is interactive and can block non-interactive deployments.

## Configuration (current)

Environment variables currently used:

- `HOST` (default `0.0.0.0`)
- `PORT` (default `8000`)

Other settings (DB path, CORS, auth cookie/JWT config, required languages) are currently hardcoded in `src/settings.py`.

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

`Dockerfile.core` exists, but it currently depends on `requirements/release.txt`, which is incomplete. Fix `requirements/release.txt` before using the Docker build.

## Known Gaps / Production Notes

- JWT secret is hardcoded in source (`src/settings.py`) and should be moved to environment variables.
- Cookie security/CSRF settings are disabled by default and should be tightened for production.
- Token revocation is in-memory only (lost on restart).
- No runnable automated tests are present in `tests/` at the moment.

## License

This project is licensed under the GNU General Public License v3.0 only (`GPL-3.0-only`).

- Internal/private use (without distribution): source disclosure is not required.
- If you distribute the software (modified or unmodified), you must provide source code under GPLv3, including your changes.

See `LICENSE` for the full license text.