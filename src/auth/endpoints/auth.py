from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.crud import (
    create_user,
    get_or_create_default_signup_role_with_config,
    get_user_by_username,
)
from src.auth.exceptions import InvalidCredentialsError, UsernameAlreadyExistsError
from src.auth.schemas import (
    AuthMeResponse,
    AuthMessageResponse,
    AuthTokenResponse,
    UserAuthBody,
)
from src.auth.dependencies import (
    get_request_access_token,
    get_runtime_from_request,
)
from src.auth.service import (
    hash_password,
    issue_access_token,
    revoke_token,
    verify_password,
)
from src.database import DbSession
from src.user_role.middlewares import get_current_user_with_role

auth_opened_router = APIRouter()
auth_closed_router = APIRouter()


@auth_opened_router.post(
    "/signup", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED
)
async def signup(payload: UserAuthBody, session: DbSession, request: Request):
    runtime = get_runtime_from_request(request)
    role = await get_or_create_default_signup_role_with_config(session, config=runtime.config)
    try:
        user = await create_user(
            session,
            username=payload.username,
            password_hash=hash_password(payload.password),
            role_id=role.id,
            permissions={},
        )
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    access_token = issue_access_token(user.username, security=runtime.security)
    return AuthTokenResponse(access_token=access_token)


@auth_opened_router.post("/login", response_model=AuthTokenResponse)
async def login(payload: UserAuthBody, session: DbSession, request: Request):
    user = await get_user_by_username(session, payload.username)
    if user is None or not verify_password(payload.password, user.password):
        exc = InvalidCredentialsError("Invalid credentials")
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    runtime = get_runtime_from_request(request)
    access_token = issue_access_token(user.username, security=runtime.security)
    return AuthTokenResponse(access_token=access_token)


@auth_closed_router.post("/reset", response_model=AuthMessageResponse)
async def reset_access_token(request: Request, request_token=Depends(get_request_access_token)):
    runtime = get_runtime_from_request(request)
    await revoke_token(
        request_token.token,
        security=runtime.security,
        engine=runtime.engine,
    )
    return AuthMessageResponse(message="Access token revoked. Login again.")


@auth_closed_router.get("/me", response_model=AuthMeResponse)
async def me(user_role_pair=Depends(get_current_user_with_role)):
    user, role = user_role_pair
    role_permissions = dict(role.permissions or {})
    user_permissions = dict(user.permissions or {})
    effective_permissions = dict(role_permissions)
    effective_permissions.update(user_permissions)
    return AuthMeResponse(
        id=user.id,
        username=user.username,
        role={
            "id": role.id,
            "name": role.name,
            "title_key": role.title_key,
        },
        permissions={
            "user": user_permissions,
            "role": role_permissions,
            "effective": effective_permissions,
        },
    )
