from src.i18n.translates import register_small_translates
from src.user_role.defaults import (
    ADMIN_ROLE_TITLE_KEY,
    GUEST_ROLE_TITLE_KEY,
    PLUGIN_ROLE_TITLE_KEY,
    STUDENT_ROLE_TITLE_KEY,
    SUPERADMIN_ROLE_TITLE_KEY,
    TEACHER_ROLE_TITLE_KEY,
    USER_ROLE_TITLE_KEY,
)

ROLE_TITLE_TRANSLATES: dict[str, dict[str, str]] = {
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
    USER_ROLE_TITLE_KEY: {
        "en": "User",
        "ru": "Пользователь",
        "uz": "Foydalanuvchi",
    },
    GUEST_ROLE_TITLE_KEY: {
        "en": "Guest",
        "ru": "Гость",
        "uz": "Mehmon",
    },
    TEACHER_ROLE_TITLE_KEY: {
        "en": "Teacher",
        "ru": "Преподаватель",
        "uz": "O'qituvchi",
    },
    STUDENT_ROLE_TITLE_KEY: {
        "en": "Student",
        "ru": "Студент",
        "uz": "Talaba",
    },
    PLUGIN_ROLE_TITLE_KEY: {
        "en": "Plugin",
        "ru": "Плагин",
        "uz": "Plagin",
    },
}


register_small_translates(ROLE_TITLE_TRANSLATES)
