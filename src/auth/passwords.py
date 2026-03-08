from __future__ import annotations

import hashlib
import hmac
import os
from functools import lru_cache

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

PBKDF2_ALGORITHM = "sha256"
PBKDF2_SCHEME_NAME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 100_000
PBKDF2_ITERATIONS_ENV = "PBKDF2_ITERATIONS"
_PBKDF2_TEST_OVERRIDE_ENV = "PYTEST_CURRENT_TEST"
_ARGON2_TIME_COST_ENV = "ARGON2_TIME_COST"
_ARGON2_MEMORY_COST_ENV = "ARGON2_MEMORY_COST"
_ARGON2_PARALLELISM_ENV = "ARGON2_PARALLELISM"
_TEST_ARGON2_TIME_COST = 1
_TEST_ARGON2_MEMORY_COST = 8 * 1024
_TEST_ARGON2_PARALLELISM = 1


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def _get_password_hasher() -> PasswordHash:
    if os.getenv(_PBKDF2_TEST_OVERRIDE_ENV):
        return PasswordHash(
            (
                Argon2Hasher(
                    time_cost=_get_int_env(_ARGON2_TIME_COST_ENV, _TEST_ARGON2_TIME_COST),
                    memory_cost=_get_int_env(_ARGON2_MEMORY_COST_ENV, _TEST_ARGON2_MEMORY_COST),
                    parallelism=_get_int_env(_ARGON2_PARALLELISM_ENV, _TEST_ARGON2_PARALLELISM),
                ),
            )
        )
    return PasswordHash.recommended()


@lru_cache(maxsize=1)
def _get_pbkdf2_iterations() -> int:
    raw_value = os.getenv(PBKDF2_ITERATIONS_ENV, "").strip()
    if not raw_value:
        return PBKDF2_ITERATIONS
    try:
        value = int(raw_value)
    except ValueError:
        return PBKDF2_ITERATIONS
    if os.getenv(_PBKDF2_TEST_OVERRIDE_ENV):
        return max(1, value)
    return max(PBKDF2_ITERATIONS, value)


def _pbkdf2_hex_digest(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()


def _verify_legacy_pbkdf2_password(password: str, stored_hash: str) -> bool:
    try:
        scheme_name, iteration_count_raw, salt, expected_digest = stored_hash.split("$", 3)
        if scheme_name != PBKDF2_SCHEME_NAME:
            return False
        iteration_count = int(iteration_count_raw)
    except (ValueError, TypeError):
        return False

    candidate_digest = _pbkdf2_hex_digest(password, salt, iteration_count)
    return hmac.compare_digest(candidate_digest, expected_digest)


def hash_password(password: str) -> str:
    return _get_password_hasher().hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(f"{PBKDF2_SCHEME_NAME}$"):
        return _verify_legacy_pbkdf2_password(password, stored_hash)

    try:
        return _get_password_hasher().verify(password, stored_hash)
    except Exception:
        return False
