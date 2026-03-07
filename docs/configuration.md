# Configuration Reference

## Purpose

Краткая карта основных env-переменных проекта и того, как они влияют на runtime.

## Required

- `JWT_SECRET_KEY`

Без него приложение не стартует.

## Database

- `DATABASE_URL`

По умолчанию используется локальный SQLite:

```env
DATABASE_URL=sqlite+aiosqlite:///data/db.sqlite3
```

## HTTP / CORS

- `HOST`
- `PORT`
- `CORS_ALLOW_ORIGINS`
- `CORS_ALLOW_CREDENTIALS`
- `CORS_ALLOW_METHODS`
- `CORS_ALLOW_HEADERS`

Важно:

- wildcard origin `*` запрещён
- нужно указывать явные trusted origins

## Logging / Profiling

- `REQUEST_LOG_ENABLED`
- `AUDIT_LOG_ENABLED`
- `APP_PROFILING_ENABLED`
- `APP_FUNCTION_PROFILING_ENABLED`

Рекомендация:

- для обычного локального запуска profiler лучше держать выключенным
- для расследования hot path включать его отдельно

## Rate Limit

- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_WINDOW_SECONDS`
- `RATE_LIMIT_MAX_REQUESTS`

Поведение:

- при доступном Redis rate limit использует shared state
- без Redis включается in-memory fallback

## Redis

- `REDIS_ENABLED`
- `REDIS_URL`
- `REDIS_DEFAULT_TTL_SECONDS`
- `REDIS_HEARTBEAT_ENABLED`
- `REDIS_HEARTBEAT_SCHEDULE_SECONDS`

Redis в проекте используется для:

- i18n cache
- RBAC read cache
- auth revocation shared cache
- shared rate limit state

## Bootstrap Superuser

- `BOOTSTRAP_SUPERUSER_CREATE`
- `BOOTSTRAP_SUPERUSER_USERNAME`
- `BOOTSTRAP_SUPERUSER_PASSWORD`

Если bootstrap включён, приложение при startup создаёт initial superuser, если его ещё нет.
