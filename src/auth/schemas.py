from pydantic import BaseModel, Field


class UserAuthSchema(BaseModel):
    username: str = Field(
        ...,
        min_length=5,
        max_length=128,
        pattern="^[a-zA-Z0-9]+$",
        json_schema_extra={"example": "student01"},
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        json_schema_extra={"example": "StrongPass123"},
    )

UserAuthBody = UserAuthSchema

class AuthTokenResponse(BaseModel):
    access_token: str = Field(..., json_schema_extra={"example": "eyJhbGciOi..."})
    token_type: str = Field(default="bearer", json_schema_extra={"example": "bearer"})


class AuthMessageResponse(BaseModel):
    message: str = Field(
        ...,
        json_schema_extra={"example": "Access token revoked. Login again."},
    )


class AuthMeRoleResponse(BaseModel):
    id: int
    name: str
    title_key: str


class AuthMePermissionsResponse(BaseModel):
    user: dict[str, bool]
    role: dict[str, bool]
    effective: dict[str, bool]


class AuthMeResponse(BaseModel):
    id: int
    username: str
    role: AuthMeRoleResponse
    permissions: AuthMePermissionsResponse
