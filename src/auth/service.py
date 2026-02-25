import hashlib
import hmac
import secrets

from fastapi import Request, Response

from src.settings import SECURITY

_revoked_tokens: set[str] = set()
PBKDF2_ALGORITHM = "sha256"
PBKDF2_SCHEME_NAME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 100_000


def is_token_revoked(token: str) -> bool:
    return token in _revoked_tokens


def revoke_token(token: str) -> None:
    _revoked_tokens.add(token)


def configure_token_blocklist() -> None:
    SECURITY.set_token_blocklist(is_token_revoked)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"{PBKDF2_SCHEME_NAME}${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme_name, iteration_count_raw, salt, expected_digest = stored_hash.split("$", 3)
        if scheme_name != PBKDF2_SCHEME_NAME:
            return False
        iteration_count = int(iteration_count_raw)
    except (ValueError, TypeError):
        return False

    candidate_digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iteration_count,
    ).hex()
    return hmac.compare_digest(candidate_digest, expected_digest)


def issue_access_token(username: str) -> str:
    return SECURITY.create_access_token(uid=username)


def set_access_cookie(response: Response, token: str) -> None:
    SECURITY.set_access_cookies(token, response)


def unset_access_cookie(response: Response) -> None:
    SECURITY.unset_access_cookies(response)


async def extract_access_token(request: Request) -> str:
    access_token = await SECURITY.get_access_token_from_request(request)
    return access_token.token


configure_token_blocklist()
