# TODO

## Why This File Exists

This file replaces the completed `TODO_CHECKS.md`.

The previous review pass already covered broad correctness, startup resilience,
Redis degradation, auth/RBAC basics, cache safety, and operability wiring.
That checklist is intentionally retired.

The next phase is narrower and more aggressive:

1. find real bugs and regressions
2. find measurable performance waste
3. fix safe issues in the same pass
4. leave clear notes for the next pass

## How To Use This File

1. Read this file first.
2. Pick one track:
   - `Bug Hunt`
   - `Performance`
3. Start from the unchecked highest-priority items.
4. When a file or area is reviewed:
   - change `[ ]` to `[x]`
   - add a short note with the finding, fix, or reason no change was needed
5. If behavior changes, update tests in the same pass.
6. If performance changes, record a short before/after note or another concrete proof.
7. If all unchecked items are done, continue from the latest git diff and the hottest request paths.

Legend:

- `[ ]` not yet reviewed for this objective
- `[x]` reviewed meaningfully for this objective

## Scope For This Phase

Focus on two outcomes only:

- correctness under edge cases, partial failure, stale state, and transaction drift
- lower overhead on startup and request hot paths without architectural churn

## Preserve These Behaviors Unless Intentionally Changed

- App must stay alive when Redis is absent or dies later.
- Startup may run in degraded cache mode.
- Request-id must still be returned on operational error responses.
- Invalid bearer tokens should still emit a security warning.
- Redis-backed request limiting currently fails closed with `429` if the limiter backend breaks mid-request.
- Container prestart remains the preferred one-time schema/bootstrap path for Compose workers.

## Work Rules

- Prefer concrete bugs over speculative cleanup.
- Prefer measurable waste over style-only optimization.
- Do not widen scope into refactors unless they remove a proven bug or bottleneck.
- For DB-related fixes, check transaction boundaries, duplicate queries, ordering stability, and cache invalidation.
- For performance work, check query count, repeated token decode, repeated Redis ping, large JSON serialization, and full-table seed scans.

## Bug Hunt

### Highest Priority

- [ ] `src/startup/lifespan.py`
  Notes: verify bootstrap gating, retry-after-migration path, Redis degraded startup, and repeated lifespan execution in tests/workers.

- [ ] `src/startup/bootstrap.py`
  Notes: verify transaction boundaries across role/i18n seeders, startup migration edge cases, and failure messages that may still mislead operators.

- [ ] `scripts/container_prestart.py`
  Notes: verify prestart vs worker-start behavior stays consistent and does not hide runtime drift or partial bootstrap failure.

- [ ] `src/config.py`
  Notes: check env parsing edge cases, surprising defaults, and whether new flags can disable more than their names imply.

### Auth / Security Correctness

- [ ] `src/auth/service.py`
  Notes: look for token issuance/verification mismatch, revocation edge cases, and runtime-global state leakage.

- [ ] `src/auth/dependencies.py`
  Notes: verify request-scoped caching, auth dependency reuse, and consistent `401` behavior when payload/token parsing fails.

- [ ] `src/auth/revocation.py`
  Notes: verify revocation TTL/window logic, DB fallback behavior, and stale-cache semantics.

- [ ] `src/auth/tokens.py`
  Notes: verify claim shape, expiry handling, and compatibility with revocation and current-user lookup.

### Persistence / Cache Correctness

- [ ] `src/database.py`
  Notes: verify session lifetime, rollback behavior, and default-runtime fallbacks under unusual call paths.

- [ ] `src/user_role/crud.py`
  Notes: verify role/user mutation semantics, cache invalidation, and backend-portable conflict handling.

- [ ] `src/i18n/crud.py`
  Notes: verify merge/upsert semantics, write conflicts, and cache invalidation after updates.

- [ ] `src/user_role/cache.py`
  Notes: verify cache key correctness, stale-data invalidation, and mismatch handling on list/detail paths.

- [ ] `src/i18n/cache.py`
  Notes: verify stale translation handling, cache poisoning resistance, and read-after-write behavior.

### HTTP / Operational Correctness

- [ ] `src/app.py`
  Notes: verify middleware ordering, runtime selection, and health/ready behavior when runtime state is swapped in tests.

- [ ] `src/http/observability.py`
  Notes: verify actor extraction, audit log correctness, and error-path behavior under bad tokens or partial request state.

- [ ] `src/utils/cache.py`
  Notes: verify heartbeat lifecycle, availability transitions, and client failure handling under reconnect loops.

- [ ] `src/utils/rate_limit.py`
  Notes: verify fail-closed behavior is consistent and does not leak script/runtime errors as `500`.

## Performance

### Request Hot Paths

- [ ] `src/auth/dependencies.py`
  Notes: measure repeated token decode / payload lookup work per request and remove duplicate verification if safe.

- [ ] `src/http/observability.py`
  Notes: check whether request logging or actor extraction duplicates auth work already done elsewhere in the same request.

- [ ] `src/user_role/middlewares.py`
  Notes: check query count and whether current user + role resolution can regress into repeated DB work.

### RBAC / i18n Read Paths

- [ ] `src/user_role/crud.py`
  Notes: measure list/detail query count, ordering cost, eager-load behavior, and unnecessary object refreshes.

- [ ] `src/user_role/cache.py`
  Notes: measure cache miss vs hit overhead, payload size, and invalidation fan-out.

- [ ] `src/i18n/crud.py`
  Notes: measure list and upsert overhead, especially around large JSON payloads and repeated full scans.

- [ ] `src/i18n/cache.py`
  Notes: check serialization cost, cache stampede risk, and whether detail/list endpoints duplicate work on misses.

### Startup / Bootstrap Cost

- [ ] `src/startup/bootstrap.py`
  Notes: measure cold-start DB work and identify repeated select-all scans during seed flow.

- [ ] `src/user_role/bootstrap.py`
  Notes: check whether role seeding or permission backfill scales poorly with larger role sets.

- [ ] `src/i18n/bootstrap.py`
  Notes: check whether translation seeding performs avoidable full-table reads or redundant registry loads.

### Infra / Logging Overhead

- [ ] `src/utils/cache.py`
  Notes: check whether startup ping + heartbeat creates avoidable Redis work, especially when Redis is down.

- [ ] `src/utils/rate_limit.py`
  Notes: measure request-path Redis round trips and script loading behavior under steady state.

- [ ] `src/utils/structured_logging.py`
  Notes: verify logger setup stays lazy and that structured log formatting is not doing unnecessary work on disabled log levels.

## Suggested Evidence To Capture

For bug-fix passes:

- exact failing path
- why current behavior is wrong
- targeted regression test that proves the fix

For performance passes:

- exact endpoint or startup path
- before/after query count, timing, or serialization reduction
- note whether the gain is request-path, startup-path, or operational-noise reduction

## If This File Is Opened Later

Use this prompt:

> Continue from `TODO.md`.
> Work one track at a time: `Bug Hunt` or `Performance`.
> Start from the highest-priority unchecked items.
> For each reviewed area:
> 1. identify a concrete bug, regression risk, or measurable performance issue
> 2. fix it if safe
> 3. add or update targeted tests
> 4. write a short note so the next pass has an obvious starting point
> Preserve Redis degradation behavior and avoid unnecessary architectural churn.
