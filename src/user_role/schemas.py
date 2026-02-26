from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, model_validator

from src.user_role.permission import get_unknown_permission_keys


PermissionMap = dict[str, bool]


class PermissionSpec(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    description: str | None = None
    default: bool = False
    role_defaults: PermissionMap = Field(default_factory=dict)


class PermissionPatchSchema(RootModel[dict[str, StrictBool]]):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "rbac_can_manage_permissions": True,
                "i18n_can_create_small": True,
                "i18n_can_patch_small": True,
                "i18n_can_create_large": False,
                "i18n_can_patch_large": False,
            }
        }
    )

    @model_validator(mode="after")
    def validate_known_permission_keys(self):
        unknown_keys = get_unknown_permission_keys(dict(self.root))
        if unknown_keys:
            raise ValueError(f"Unknown permission keys: {', '.join(unknown_keys)}")
        return self


class RoleRegistrySchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "ContentEditor",
                "permissions": {
                    "i18n_can_create_small": True,
                    "i18n_can_patch_small": True,
                    "i18n_can_create_large": False,
                    "i18n_can_patch_large": False,
                    "rbac_can_manage_permissions": False,
                },
            }
        }
    )

    name: str = Field(min_length=1, max_length=128)
    permissions: PermissionMap = Field(default_factory=dict)


class RoleResponseSchema(BaseModel):
    id: int
    name: str
    title_key: str
    permissions: PermissionMap = Field(default_factory=dict)


class UserResponseSchema(BaseModel):
    id: int
    username: str
    role_id: int
    permissions: PermissionMap = Field(default_factory=dict)


class RoleCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    title_key: str = Field(min_length=1, max_length=128)


class RoleUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    title_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_non_empty_patch(self):
        if self.name is None and self.title_key is None:
            raise ValueError("At least one field must be provided")
        return self


class AdminUserCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        ...,
        min_length=5,
        max_length=128,
        pattern="^[a-zA-Z0-9]+$",
    )
    password: str = Field(..., min_length=8, max_length=128)
    role_id: int = Field(..., gt=0)


class AdminUserUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=5, max_length=128, pattern="^[a-zA-Z0-9]+$")
    role_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_non_empty_patch(self):
        if self.username is None and self.role_id is None:
            raise ValueError("At least one field must be provided")
        return self


class AdminUserPasswordSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(..., min_length=8, max_length=128)