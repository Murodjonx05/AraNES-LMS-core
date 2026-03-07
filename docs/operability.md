# Operability Notes

## Health Endpoints

- `GET /health`
- `GET /ready`

`/health`:

- лёгкий process-level endpoint
- показывает базовый статус сервиса и Redis

`/ready`:

- проверяет доступность базы данных
- возвращает `503`, если база недоступна
- не раскрывает raw DB exception text наружу

## Logging

### Request Log

Logger:

- `aranes.request`

Пишет:

- `request_id`
- method/path
- status code
- elapsed time
- client host
- actor subject, если он доступен

### Audit Log

Logger:

- `aranes.audit`

Пишется для mutating admin-sensitive endpoint-ов.

## Redis Health

Если Redis включён:

- приложение пингует его
- heartbeat пытается отслеживать recovery/failure

Если Redis недоступен:

- приложение не должно падать
- cache/rate-limit paths переходят на fallback behaviour

## Request ID

Middleware добавляет `X-Request-ID` в response.

Если входящий request уже содержит `x-request-id`, он переиспользуется.
