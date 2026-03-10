# Анализ проекта AraNES-LMS-core

## Статус документа

Этот файл описывает текущее состояние архитектуры на уровне обзора и сознательно не фиксирует
быстро стареющие цифры вроде `N passed in Xs`. Для фактического состояния ориентируйся на:

- [README.md](/run/media/aestra/data/PYTHON/lms/README.md)
- текущие workflow-файлы в [`.github/workflows/ci.yml`](/run/media/aestra/data/PYTHON/lms/.github/workflows/ci.yml) и [`.github/workflows/cd.yml`](/run/media/aestra/data/PYTHON/lms/.github/workflows/cd.yml)
- код в `src/` и тесты в `tests/`

## Что реально есть в проекте сейчас

### Архитектура

- FastAPI + async SQLAlchemy + Alembic
- `RuntimeContext` для `config/security/engine/session_factory/cache_service`
- разделение на домены: `auth`, `user_role`, `i18n`, `plugins`, `startup`, `utils`, `http`
- env-driven config через `src/config.py`

### Auth

- `signup`, `login`, `reset`, `me`
- Bearer JWT только в headers
- revocation хранится в БД (`auth_revoked_token_jtis`)
- поверх БД есть локальный memory cache и shared Redis cache

### RBAC

- CRUD ролей
- CRUD пользователей
- role registry
- role permissions + user overrides
- read permissions вынесены отдельно (`rbac_roles_read`, `rbac_users_read`)

### i18n

- `small` и `large` translation storage
- bootstrap registry + seed default translations
- Redis read-through cache для list/item endpoints

### Plugins

- API управления плагинами: `GET /api/v1/plugins`, `PATCH /api/v1/plugins/{name}` (требуется `rbac_can_manage_permissions`)
- таблица `plugin_mappings` для хранения включённых плагинов и префиксов (когда шлюз не используется)
- опциональный **plugin gateway** (`gateway_server/`): отдельный процесс, обнаруживает сервисы по `manifest.json` в `services/`, запускает их как subprocess, отдаёт `GET /services` и проксирует запросы под `/plg/{name}/...`
- демо-сервисы: `demo_fastapi`, `demo_flask`, `demo_node` в `services/`

### Operations

- `GET /health`
- `GET /ready`
- structured request logging
- audit logging для mutating admin-sensitive actions (в т.ч. `/api/v1/plugins`)
- Redis-backed rate limit при доступном Redis, с in-memory fallback

### Delivery

- CI через GitHub Actions: lint + tests + docker build
- CD через GitHub Actions: publish Docker image в GHCR

## Сильные стороны

- Чёткое доменное разделение без большой “свалки” логики
- Нормальный runtime/bootstrap слой
- Реальные integration tests на auth/RBAC/i18n/operability
- База для эксплуатационной зрелости уже есть: readiness, logging, migrations, cache fallback

## Текущие ограничения

- SQLite остаётся default локальной БД и не является финальным решением для высокой конкурентной нагрузки
- profiler и perf-лог нужно читать аккуратно: цифры чувствительны к машине, flags и test setup
- Redis остаётся optional зависимостью; при его отключении часть оптимизаций переходит на fallback path

## Практический вывод

Сейчас это уже не “черновой backend”, а рабочий backend-core с нормальной структурой, тестами,
операционным базисом, плагинами/шлюзом и минимальным CI/CD. Дальнейшие улучшения будут уже не про базовую
жизнеспособность, а про:

- дальнейшую оптимизацию hot-path
- ужесточение production policy
- выравнивание документации и поддержание её в актуальном состоянии
- при необходимости — расширение модели плагинов (например, in-process роутеры рядом с gateway)
