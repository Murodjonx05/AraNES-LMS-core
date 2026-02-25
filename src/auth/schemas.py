from pydantic import BaseModel, Field
from fastapi import Depends
from typing import Annotated

class UserAuthSchema(BaseModel):
    username: str = Field(
        ...,
        min_length=5,
        max_length=128,
        pattern="^[a-zA-Z0-9]+$",
        example="student01"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        example="StrongPass123"
    )

UserAuthDep = Annotated[UserAuthSchema, Depends()]

class AuthTokenResponse(BaseModel):
    access_token: str = Field(..., example="eyJhbGciOi...")
    token_type: str = Field(default="bearer", example="bearer")

class LogoutResponse(BaseModel):
    message: str = Field(..., example="Logged out successfully")