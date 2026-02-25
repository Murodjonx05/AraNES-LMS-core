from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.auth.crud import create_user, get_or_create_default_signup_role, get_user_by_username
from src.auth.exceptions import InvalidCredentialsError, UsernameAlreadyExistsError
from src.auth.schemas import AuthTokenResponse, LogoutResponse, UserAuthDep
from src.auth.service import (
    extract_access_token,
    hash_password,
    issue_access_token,
    revoke_token,
    set_access_cookie,
    unset_access_cookie,
    verify_password,
)
from src.database import DbSession
from src.settings import SECURITY

auth_router = APIRouter()


@auth_router.post("/signup", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserAuthDep, response: Response, session: DbSession):
    role = await get_or_create_default_signup_role(session)
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

    token = issue_access_token(user.username)
    set_access_cookie(response, token)
    return AuthTokenResponse(access_token=token)


@auth_router.post("/login", response_model=AuthTokenResponse)
async def login(payload: UserAuthDep, response: Response, session: DbSession):
    user = await get_user_by_username(session, payload.username)
    if user is None or not verify_password(payload.password, user.password):
        exc = InvalidCredentialsError("Invalid credentials")
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token = issue_access_token(user.username)
    set_access_cookie(response, token)
    return AuthTokenResponse(access_token=token)


@auth_router.post(
    "/logout",
    response_model=LogoutResponse,
    dependencies=[Depends(SECURITY.access_token_required)],
)
async def logout(request: Request, response: Response):
    token = await extract_access_token(request)
    revoke_token(token)
    unset_access_cookie(response)
    return LogoutResponse(message="Logged out successfully")


@auth_router.get("/protected", dependencies=[Depends(SECURITY.access_token_required)])
def protected():
    return {"message": "Hello World"}
