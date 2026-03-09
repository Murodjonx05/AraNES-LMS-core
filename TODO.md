# TODO

## Why This File Exists

This file replaces the completed bug/performance checklist.

The next phase is narrower:

1. reduce total `pytest -q` wall time
2. reduce the worst per-test outliers first
3. keep coverage semantics intact while removing redundant setup/call work
4. leave concrete notes for the next optimization pass

## Baseline Profile

Current baseline from `pytest -q --profile --profile-top=30`:

- `244 passed in 2.30s`
- hottest setup outlier: `tests/integration/test_auth_protection.py::test_me_requires_access_token` at `182.07ms`
- hottest call-path tests are concentrated in:
  - `tests/integration/test_auth_protection.py`
  - `tests/integration/test_rbac_i18n_protection.py`
  - `tests/integration/test_operability.py`
  - `tests/integration/test_startup_bootstrap.py`
  - `tests/auth/test_auth_service.py`

Use this profile as the initial before-state until a newer run replaces it.

## How To Use This File

1. Read this file first.
2. Start from the highest-priority unchecked items.
3. When a file or area is reviewed:
   - change `[ ]` to `[x]`
   - add a short note with the optimization, measured gain, or reason no safe change was made
4. If a test is rewritten or split, preserve the original behavior coverage.
5. Prefer fixture reuse, helper extraction, and duplicate setup removal before changing app code.
6. If app code is changed for test speed, keep the change production-safe and measurable.
7. After each meaningful pass, rerun `pytest -q --profile --profile-top=30` and update the notes.

Legend:

- `[ ]` not yet reviewed for this objective
- `[x]` reviewed meaningfully for this objective

## Scope For This Phase

Focus on test-speed work only:

- expensive integration setup
- repeated login/bootstrap flows
- repeated app/runtime construction
- repeated schema/bootstrap work inside tests
- CPU-heavy security helpers under test
- avoidable Redis/cache/rate-limit work during tests

## Preserve These Behaviors Unless Intentionally Changed

- Integration tests must still exercise the real auth/RBAC/i18n protection paths.
- Startup/bootstrap tests must still prove schema/bootstrap behavior, not a mocked substitute.
- Do not weaken production Argon2 settings globally to make tests faster.
- Redis degradation behavior must stay covered.
- Request-id and audit-log assertions must stay covered.
- Legacy-token compatibility and stable-uid behavior must stay covered.

## Work Rules

- Prefer removing duplicated setup over micro-optimizing assertions.
- Prefer fixture scope changes only when they do not leak state across tests.
- Keep DB isolation explicit; do not trade correctness for speed blindly.
- For auth-heavy tests, check whether repeated signup/login/me flows can share helper setup.
- For integration clients, check whether app creation or runtime bootstrap is happening more often than needed.
- Record setup/call/teardown wins separately when possible.

## Highest Priority Outliers

- [ ] `tests/integration/test_auth_protection.py::test_me_requires_access_token`
  Notes: hottest test by a large margin and almost all cost is in setup (`179.76ms` of `182.07ms`). Check client/runtime fixture scope, app construction, DB bootstrap, and whether unauthenticated auth-protection checks can reuse a cheaper fixture path.

- [ ] `tests/integration/test_rbac_i18n_protection.py::test_superuser_can_manage_roles_and_users_crud`
  Notes: heavy call-path test (`103.94ms` call). Check how many HTTP requests and login/setup steps it performs, and whether repeated auth/admin helper steps can be collapsed without losing CRUD coverage.

- [ ] `tests/integration/test_auth_protection.py::test_me_uses_stable_user_id_claim_after_username_change_and_reuse`
  Notes: expensive auth flow (`93.77ms` call). Likely repeated signup/login/rename/relogin work. Check whether helper calls can reuse issued tokens, direct setup helpers, or fewer round trips while keeping the same behavioral proof.

- [ ] `tests/integration/test_operability.py::test_audit_log_uses_stable_uid_after_username_rename_and_reuse`
  Notes: similar expensive auth+mutation flow (`88.02ms` call). Check overlap with the previous stable-uid test and whether shared setup helpers can remove redundant requests and bootstrap cost.

- [ ] `tests/integration/test_auth_protection.py::test_login_me_and_reset_access_flow`
  Notes: expensive chained flow (`87.20ms` call). Check for duplicate login/reset/me requests that could be reduced while preserving end-to-end semantics.

- [ ] `tests/integration/test_startup_bootstrap.py::test_startup_bootstrap_succeeds_with_enforced_foreign_keys`
  Notes: startup-path outlier (`71.78ms` call). Check whether the test recreates app/runtime/schema more than necessary or pays repeated Alembic/bootstrap work that can be isolated once per file.

- [ ] `tests/auth/test_auth_service.py::test_password_hasher_clamps_weak_argon2_env_values_outside_pytest`
  Notes: unit test is CPU-heavy (`67.89ms` call). Check whether the test is exercising real hashing work unnecessarily when it only needs to prove config clamping behavior.

## Integration Suites

### Auth Integration

- [ ] `tests/integration/test_auth_protection.py`
  Notes: review the whole file for repeated client creation, signup/login helpers, token issuance, and user lifecycle setup. This file contains both the hottest setup outlier and several top call-path tests.

- [ ] `tests/integration/test_operability.py`
  Notes: review auth-heavy operability tests for repeated setup overlaps with auth protection tests, especially stable-uid and audit-log scenarios.

### RBAC / i18n Integration

- [ ] `tests/integration/test_rbac_i18n_protection.py`
  Notes: multiple top entries come from this file. Check whether protected-endpoint matrices can share seeded users/tokens/roles more efficiently.

- [ ] `tests/integration/test_rbac_cache.py`
  Notes: medium-cost integration tests still spend several milliseconds in setup. Check whether cache backend fakes, seeded users, and app/runtime fixtures are recreated more often than needed.

- [ ] `tests/integration/test_i18n_cache.py`
  Notes: similar review for repeated setup and repeated cache-service/runtime bootstrap across cases.

### Startup / Bootstrap Integration

- [ ] `tests/integration/test_startup_bootstrap.py`
  Notes: isolate whether cost is in DB creation, startup lifespan, schema migration, or FK enforcement setup. Optimize the slowest part without reducing what the test proves.

## Shared Fixture and Helper Layer

- [ ] `tests/conftest.py`
  Notes: inspect global fixtures for app/runtime/client/database creation cost. Check scope, repeated default runtime construction, and whether expensive setup is performed even for tests that do not need it.

- [ ] `tests/integration/conftest.py`
  Notes: review integration-specific client/runtime fixtures for repeated startup/bootstrap/cache initialization and teardown overhead.

- [ ] auth test helpers and login/signup helpers
  Notes: extract or tighten shared helpers if multiple integration tests are repeating the same HTTP setup dance manually.

- [ ] app/runtime test construction path
  Notes: review whether `create_app(...)`, startup lifespan, metrics/instrumentation, and cache heartbeat are doing unnecessary work in test mode.

## Unit-Test CPU Hotspots

- [ ] `tests/auth/test_auth_service.py`
  Notes: review hashing/revocation tests for unnecessary real crypto work, repeated service construction, or repeated DB/cache setup where a smaller fake would preserve the same proof.

- [ ] `src/auth/service.py`
  Notes: only if needed for the tests above. Check whether test-only heavy paths are caused by avoidable service initialization or password hasher construction.

## Evidence To Capture

For each optimization pass, record:

- exact test or fixture that was hot
- whether the waste was setup, call, or teardown
- before/after timing from `pytest --profile`
- whether the gain came from fixture reuse, fewer requests, less bootstrap, or less CPU work

## If This File Is Opened Later

Use this prompt:

> Continue from `TODO.md`.
> Focus only on test-suite optimization.
> Start from the highest-priority unchecked items.
> Prefer removing repeated setup and repeated HTTP/bootstrap work before changing app behavior.
> Preserve coverage semantics and update timing notes after each pass.
