from pydantic import BaseModel, ConfigDict, Field, RootModel


PermissionMap = dict[str, bool]


class PermissionSpec(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    description: str | None = None
    default: bool = False
    role_defaults: PermissionMap = Field(default_factory=dict)


class PermissionPatchSchema(RootModel[PermissionMap]):
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


class RoleRegistrySchema(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    permissions: PermissionMap = Field(default_factory=dict)
