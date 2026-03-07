class DuplicatePermissionKeysError(Exception):
    def __init__(self, duplicate_keys: list[str]):
        self.duplicate_keys = duplicate_keys
        super().__init__("Permission keys already exist and cannot be overwritten")


class RoleNotFoundError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class RoleAlreadyExistsError(Exception):
    pass


class RoleInUseError(Exception):
    def __init__(self, user_count: int):
        self.user_count = user_count
        super().__init__(f"Role is assigned to {user_count} user(s)")


class SuperAdminRoleImmutableError(Exception):
    pass


class SelfDeleteForbiddenError(Exception):
    pass


class InvalidPermissionPatchError(Exception):
    def __init__(
        self,
        *,
        unknown_keys: list[str] | None = None,
        non_boolean_keys: list[str] | None = None,
    ):
        self.unknown_keys = sorted(unknown_keys or [])
        self.non_boolean_keys = sorted(non_boolean_keys or [])

        details: list[str] = []
        if self.unknown_keys:
            details.append(f"unknown keys: {', '.join(self.unknown_keys)}")
        if self.non_boolean_keys:
            details.append(f"non-boolean values: {', '.join(self.non_boolean_keys)}")
        super().__init__("Invalid permission patch" + (f" ({'; '.join(details)})" if details else ""))
