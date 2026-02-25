# How To Create Translates For Keys (i18n)

## Goal

Создать переводы для ключей (например `role.student.title`), зарегистрировать их в i18n registry и автоматически загрузить в БД.

## Where Key Comes From

Обычно key хранится как `CONST` в доменном модуле.

For example (`src/user_role/defaults.py`, role titles):

```python
SUPERADMIN_ROLE_TITLE_KEY = "role.super_admin.title"
ADMIN_ROLE_TITLE_KEY = "role.admin.title"
STUDENT_ROLE_TITLE_KEY = "role.student.title"
```

Это лучше, чем дублировать строку в нескольких местах.

## Why We Use `CONST` And Why It Is In `defaults.py`

Мы вынесли `title_key` в `CONST` (например `SUPERADMIN_ROLE_TITLE_KEY`, `STUDENT_ROLE_TITLE_KEY`) и храним его в `src/user_role/defaults.py`, потому что это:

- **single source of truth** для role key'ов
- используется сразу в нескольких местах:
  - `DEFAULT_ROLES` (seed ролей)
  - `DEFAULT_SIGNUP_ROLE_TITLE_KEY`
  - `src/user_role/translates.py` (переводы)
  - i18n seed / registry
- уменьшает риск опечаток в строковых ключах (`"role.student.title"`)
- упрощает рефакторинг (поменял key в одном месте)

Почему именно `defaults.py`:

- там уже лежат default роли (`id`, `name`, `title_key`)
- `title_key` относится к default role definition, а не к i18n тексту
- `translates.py` должен хранить **тексты**, а не определять ключи ролей

Идея разделения:

- `defaults.py` -> **какие key существуют**
- `translates.py` -> **какие тексты соответствуют этим key**

## Step 1. Create Translates In Your Module

Создай файл `translates.py` в модуле.

For example (`src/user_role/translates.py`, real role-title registration):

```python
from src.i18n.translates import register_title_translates
from src.user_role.defaults import (
    ADMIN_ROLE_TITLE_KEY,
    STUDENT_ROLE_TITLE_KEY,
    SUPERADMIN_ROLE_TITLE_KEY,
)

ROLE_TITLE_TRANSLATES = {
    SUPERADMIN_ROLE_TITLE_KEY: {
        "en": "Super Admin",
        "ru": "Супер админ",
        "uz": "Super admin",
    },
    ADMIN_ROLE_TITLE_KEY: {
        "en": "Admin",
        "ru": "Админ",
        "uz": "Admin",
    },
    STUDENT_ROLE_TITLE_KEY: {
        "en": "Student",
        "ru": "Студент",
        "uz": "Talaba",
    },
}

register_title_translates(ROLE_TITLE_TRANSLATES)
```

Что важно:

- ключи лучше брать из `CONST`
- в конце файла нужно вызвать `register_title_translates(...)`

## Step 2. Registry (Global i18n Storage Before DB Seed)

Registry находится в `src/i18n/translates.py`:

- `register_title_translates(mapping)` — регистрирует переводы
- `get_registered_title_translates()` — возвращает все зарегистрированные переводы

Это позволяет нескольким модулям добавлять свои переводы независимо:

- `src/user_role/translates.py`
- `src/course/translates.py`
- `src/auth/translates.py`

## Step 3. Load Registered Translates Into DB

Загрузка в БД происходит через `src/i18n/bootstrap.py`.

Сейчас сидирование:

1. импортирует модули, которые регистрируют переводы
2. берет переводы из registry
3. создает записи в `translate_small`, если их еще нет

Важно:

- существующие записи не перезаписываются
- создаются только отсутствующие ключи

## Step 4. Add New Module Translates (Example)

For example (`src/course/translates.py`):

```python
from src.i18n.translates import register_title_translates

COURSE_TITLE_TRANSLATES = {
    "course.title": {
        "en": "Course",
        "ru": "Курс",
        "uz": "Kurs",
    }
}

register_title_translates(COURSE_TITLE_TRANSLATES)
```

После этого нужно подключить модуль-регистратор в `src/i18n/bootstrap.py`:

```python
import src.course.translates  # noqa: F401
```

## How To Check It Works

1. Перезапусти приложение
2. Сидирование выполнится на startup
3. Проверь:

- `GET /api/v1/i18n/small`

Ты должен увидеть свои ключи и переводы.

## Best Practice

- Ключи (`..._TITLE_KEY`) хранить как `CONST`
- Тексты переводов хранить в `translates.py` доменного модуля
- Регистрацию делать в конце `translates.py`
- Сидирование держать в `src/i18n/bootstrap.py`
