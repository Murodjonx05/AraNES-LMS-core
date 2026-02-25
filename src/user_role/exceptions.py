class DuplicatePermissionKeysError(Exception):
    def __init__(self, duplicate_keys: list[str]):
        self.duplicate_keys = duplicate_keys
        super().__init__("Permission keys already exist and cannot be overwritten")


class RoleNotFoundError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class SuperAdminRoleImmutableError(Exception):
    pass
