# Release Notes: Auth (Bearer JWT + Revocation)

## Current Auth Endpoints

- `POST /api/v1/auth/auth/signup`
- `POST /api/v1/auth/auth/login`
- `POST /api/v1/auth/auth/reset` (revoke current access token)
- `GET /api/v1/auth/auth/me` (requires access token)

## Current Auth Mode

Backend is configured for **Bearer JWT in headers only**.

- `Authorization: Bearer <access_token>`
- `AuthXConfig.JWT_TOKEN_LOCATION=["headers"]`

Cookie-based auth is **not enabled** in the current implementation.

## Token Revocation

`/reset` revokes the current access token by storing its `jti` (JWT ID) until token expiry.

- revoked tokens are checked via AuthX blocklist callback
- revocation data is stored in database table `auth_revoked_token_jtis`
- expired revocation records are cleaned up during writes

## JWT Compatibility Fix

Revocation parsing now accepts JWT `exp` in multiple formats:

- `datetime`
- ISO datetime string
- numeric Unix timestamp (`int` / `float`)

This fixes revocation for tokens where `exp` is encoded/decoded as a numeric claim (for example `1772098145.865263`).

## Usage Example

```http
GET /api/v1/auth/auth/me
Authorization: Bearer <access_token>
```

```http
POST /api/v1/auth/auth/reset
Authorization: Bearer <access_token>
```

After `/reset`, the same token should return `401` on protected endpoints.
