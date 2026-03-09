from functools import lru_cache

I18N_CAN_READ_SMALL = "i18n_can_read_small"
I18N_CAN_CREATE_SMALL = "i18n_can_create_small"
I18N_CAN_PATCH_SMALL = "i18n_can_patch_small"
I18N_CAN_READ_LARGE = "i18n_can_read_large"
I18N_CAN_CREATE_LARGE = "i18n_can_create_large"
I18N_CAN_PATCH_LARGE = "i18n_can_patch_large"


I18N_ROLE_PERMISSION_DEFAULTS: dict[str, dict[str, bool]] = {
    "SuperAdmin": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: True,
        I18N_CAN_PATCH_SMALL: True,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: True,
        I18N_CAN_PATCH_LARGE: True,
    },
    "Admin": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: True,
        I18N_CAN_PATCH_SMALL: True,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: True,
        I18N_CAN_PATCH_LARGE: True,
    },
    "Teacher": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: True,
        I18N_CAN_PATCH_SMALL: True,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: True,
        I18N_CAN_PATCH_LARGE: True,
    },
    "Student": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: False,
        I18N_CAN_PATCH_SMALL: False,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: False,
        I18N_CAN_PATCH_LARGE: False,
    },
    "User": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: False,
        I18N_CAN_PATCH_SMALL: False,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: False,
        I18N_CAN_PATCH_LARGE: False,
    },
    "Guest": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: False,
        I18N_CAN_PATCH_SMALL: False,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: False,
        I18N_CAN_PATCH_LARGE: False,
    },
    "PLUGIN": {
        I18N_CAN_READ_SMALL: True,
        I18N_CAN_CREATE_SMALL: True,
        I18N_CAN_PATCH_SMALL: False,
        I18N_CAN_READ_LARGE: True,
        I18N_CAN_CREATE_LARGE: True,
        I18N_CAN_PATCH_LARGE: False,
    },
}


@lru_cache(maxsize=None)
def get_i18n_role_permission_defaults(role_name: str) -> dict[str, bool]:
    return dict(I18N_ROLE_PERMISSION_DEFAULTS.get(role_name, {}))
