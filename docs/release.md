# Release Notes: Auth (Signup/Login/Logout + Cookie/Bearer)

## Что добавлено

В проект добавлены базовые auth endpoints:

- `POST /api/v1/auth/auth/signup`
- `POST /api/v1/auth/auth/login`
- `POST /api/v1/auth/auth/logout`
- `GET /api/v1/auth/auth/protected` (проверка доступа)

## Что изменилось в авторизации

Сейчас backend работает в **hybrid режиме** (два режима сразу):

- `Bearer token` через заголовок `Authorization`
- `access_token` через `Cookie`

Это включено в `AuthXConfig`:

- `JWT_TOKEN_LOCATION=["headers", "cookies"]`

## Как это использовать

### Для сайтов (web)

Рекомендуется использовать **cookie**:

- браузер сам отправляет cookie
- удобно для обычного frontend/backend
- можно сделать `HttpOnly` для лучшей защиты

### Для мобильных приложений

Рекомендуется использовать **Bearer token** в headers:

- клиент сам контролирует токен
- удобно для mobile API
- не зависит от cookie-политик браузера

## Поведение текущих endpoints

### `signup`

- создаёт пользователя
- хеширует пароль (PBKDF2 SHA-256)
- возвращает `access_token` в JSON
- одновременно ставит `access_token` в cookie

### `login`

- проверяет логин/пароль
- возвращает `access_token` в JSON
- одновременно ставит `access_token` в cookie

### `logout`

- требует действующий access token
- добавляет текущий token в blocklist (revoked)
- удаляет `access_token` cookie

## Важный нюанс (текущая реализация)

`logout` использует **in-memory blocklist**:

- после перезапуска сервера revoked tokens забываются

Для production лучше хранить blocklist в:

- Redis
- или базе данных

## Текущие dev-настройки cookie

Для локальной разработки сейчас включено:

- `JWT_COOKIE_SECURE=False`
- `JWT_COOKIE_CSRF_PROTECT=False`

Это сделано для удобства локального HTTP.

## Что нужно включить в production

Для сайта (cookie auth) обязательно:

- `JWT_COOKIE_SECURE=True`
- `JWT_COOKIE_HTTP_ONLY=True`
- `JWT_COOKIE_CSRF_PROTECT=True`
- корректный `SameSite` (`lax` / `none` в зависимости от frontend домена)

## Итог

Текущая схема подходит для обоих клиентов:

- `web -> cookie`
- `mobile -> bearer token`

Backend уже поддерживает оба варианта одновременно.
