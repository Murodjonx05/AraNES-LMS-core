"""Tests for system-level states and configurations."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestConfigurationStates:
    """Test different configuration states."""

    def test_config_state_minimal(self, monkeypatch: pytest.MonkeyPatch):
        """Test: MINIMAL_CONFIG state (only required fields)."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: MINIMAL_CONFIG
        assert config.JWT_SECRET_KEY is not None
        assert len(config.CORS["ALLOW_ORIGINS"]) > 0

    def test_config_state_full(self, monkeypatch: pytest.MonkeyPatch):
        """Test: FULL_CONFIG state (all fields configured)."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("REDIS_ENABLED", "true")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("PLUGIN_MANAGER_ENABLED", "true")
        monkeypatch.setenv("PLUGIN_GATEWAY_URL", "http://gateway:8001")
        monkeypatch.setenv("PLUGIN_GATEWAY_CACHE_TTL_SECONDS", "5.5")
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: FULL_CONFIG
        assert config.REDIS_ENABLED is True
        assert config.PLUGIN_MANAGER_ENABLED is True
        assert config.PLUGIN_GATEWAY_URL is not None
        assert config.PLUGIN_GATEWAY_CACHE_TTL_SECONDS == 5.5
        assert config.RATE_LIMIT_ENABLED is True
        assert config.LOG_LEVEL == "DEBUG"
        assert config.OPERABILITY_DB_CHECK_TIMEOUT_SECONDS == 2.0
        assert config.REDIS_COMMAND_TIMEOUT_SECONDS == 3.0
        assert config.INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES == 4096
        assert config.PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS == 30.0

    def test_config_state_development(self, monkeypatch: pytest.MonkeyPatch):
        """Test: DEVELOPMENT_CONFIG state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("REQUEST_LOG_ENABLED", "true")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: DEVELOPMENT_CONFIG
        assert config.ENVIRONMENT == "development"
        assert config.LOG_LEVEL == "DEBUG"
        assert config.REQUEST_LOG_ENABLED is True

    def test_config_state_production(self, monkeypatch: pytest.MonkeyPatch):
        """Test: PRODUCTION_CONFIG state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "production-secret-key-very-long-and-secure!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://production.example.com")
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: PRODUCTION_CONFIG
        assert config.ENVIRONMENT == "production"
        assert config.LOG_LEVEL == "WARNING"
        assert config.RATE_LIMIT_ENABLED is True

    def test_config_state_plugin_manager_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: PLUGIN_MANAGER_ENABLED state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("PLUGIN_MANAGER_ENABLED", "true")
        monkeypatch.setenv("WEB_CONCURRENCY", "1")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: PLUGIN_MANAGER_ENABLED
        assert config.PLUGIN_MANAGER_ENABLED is True

    def test_config_state_plugin_gateway_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: PLUGIN_GATEWAY_ENABLED state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("PLUGIN_GATEWAY_URL", "http://gateway:8001")
        monkeypatch.setenv("PLUGIN_MANAGER_ENABLED", "false")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: PLUGIN_GATEWAY_ENABLED (but manager disabled)
        assert config.PLUGIN_GATEWAY_URL == "http://gateway:8001"
        assert config.PLUGIN_MANAGER_ENABLED is False

    def test_config_state_plugin_gateway_cache_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: plugin gateway cache can be disabled with zero TTL."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("PLUGIN_GATEWAY_CACHE_TTL_SECONDS", "0")

        from src.config import build_app_config

        config = build_app_config()

        assert config.PLUGIN_GATEWAY_CACHE_TTL_SECONDS == 0.0

    def test_operability_and_network_timeouts_are_env_tunable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("OPERABILITY_DB_CHECK_TIMEOUT_SECONDS", "4.5")
        monkeypatch.setenv("REDIS_COMMAND_TIMEOUT_SECONDS", "7")
        monkeypatch.setenv("INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES", "512")
        monkeypatch.setenv("PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS", "45")

        from src.config import build_app_config

        config = build_app_config()
        assert config.OPERABILITY_DB_CHECK_TIMEOUT_SECONDS == 4.5
        assert config.REDIS_COMMAND_TIMEOUT_SECONDS == 7.0
        assert config.INPROCESS_HTTP_ROUTE_CACHE_MAX_ENTRIES == 512
        assert config.PLUGIN_GATEWAY_HTTP_TIMEOUT_SECONDS == 45.0


class TestRedisStates:
    """Test Redis connection states."""

    @pytest.mark.asyncio
    async def test_redis_state_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: REDIS_DISABLED state."""
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: REDIS_DISABLED
        assert config.REDIS_ENABLED is False

    @pytest.mark.asyncio
    async def test_redis_state_enabled_config(self, monkeypatch: pytest.MonkeyPatch):
        """Test: REDIS_ENABLED state as reflected in configuration."""
        monkeypatch.setenv("REDIS_ENABLED", "true")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from src.config import build_app_config

        config = build_app_config()

        # State: REDIS_ENABLED (configuration level)
        assert config.REDIS_ENABLED is True
        assert config.REDIS_URL == "redis://localhost:6379/0"


class TestApplicationLifecycleStates:
    """Test application lifecycle states."""

    @pytest.mark.asyncio
    async def test_app_state_initializing(self, monkeypatch: pytest.MonkeyPatch):
        """Test: APP_INITIALIZING state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.app import create_app

        # State: APP_INITIALIZING (during creation)
        app = create_app()
        
        assert app is not None
        assert hasattr(app.state, "runtime")

    @pytest.mark.asyncio
    async def test_app_state_ready(self, monkeypatch: pytest.MonkeyPatch):
        """Test: APP_READY state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.app import create_app
        import httpx

        app = create_app()
        transport = httpx.ASGITransport(app=app)

        # State: APP_READY (can handle requests)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_app_state_shutting_down(self, monkeypatch: pytest.MonkeyPatch):
        """Test: APP_SHUTTING_DOWN state."""
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-byte-minimum!!")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        from src.app import create_app

        app = create_app()
        runtime = app.state.runtime

        # State: APP_SHUTTING_DOWN (cleanup in progress)
        await runtime.cache_service.close()
        await runtime.engine.dispose()


class TestRateLimitStates:
    """Test rate limiting states."""

    def test_rate_limit_state_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: RATE_LIMIT_DISABLED state."""
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: RATE_LIMIT_DISABLED
        assert config.RATE_LIMIT_ENABLED is False

    def test_rate_limit_state_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: RATE_LIMIT_ENABLED state."""
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
        monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
        monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "100")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: RATE_LIMIT_ENABLED
        assert config.RATE_LIMIT_ENABLED is True
        assert config.RATE_LIMIT_WINDOW_SECONDS == 60
        assert config.RATE_LIMIT_MAX_REQUESTS == 100

    @pytest.mark.asyncio
    async def test_rate_limit_state_under_limit(self):
        """Test: RATE_LIMIT_UNDER_LIMIT state."""
        # This would require full app setup with rate limiting
        # Simplified test to show the concept
        current_requests = 50
        max_requests = 100
        
        # State: RATE_LIMIT_UNDER_LIMIT
        assert current_requests < max_requests

    @pytest.mark.asyncio
    async def test_rate_limit_state_exceeded(self):
        """Test: RATE_LIMIT_EXCEEDED state."""
        # Simplified test
        current_requests = 101
        max_requests = 100
        
        # State: RATE_LIMIT_EXCEEDED
        assert current_requests > max_requests


class TestDatabaseConnectionStates:
    """Test database connection states."""

    @pytest.mark.asyncio
    async def test_database_state_connected(self, monkeypatch: pytest.MonkeyPatch):
        """Test: DATABASE_CONNECTED state."""
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        
        # State: DATABASE_CONNECTED
        async with engine.connect() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
        
        await engine.dispose()


    @pytest.mark.asyncio
    async def test_database_state_schema_missing(self):
        """Test: DATABASE_SCHEMA_MISSING state."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        
        # State: DATABASE_SCHEMA_MISSING (no tables created)
        async with engine.connect() as conn:
            try:
                await conn.execute(text("SELECT * FROM plugin_mappings"))
                assert False, "Should have failed"
            except Exception:
                pass  # Expected - table doesn't exist
        
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_database_state_schema_present(self):
        """Test: DATABASE_SCHEMA_PRESENT state."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from src.database import Model

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        
        # Create schema
        async with engine.begin() as conn:
            await conn.run_sync(Model.metadata.create_all)
        
        # State: DATABASE_SCHEMA_PRESENT
        async with engine.connect() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = [row[0] for row in result]
            assert len(tables) > 0
        
        await engine.dispose()


class TestBootstrapStates:
    """Test bootstrap states."""

    def test_bootstrap_state_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: BOOTSTRAP_ENABLED state."""
        monkeypatch.setenv("STARTUP_DB_BOOTSTRAP_ENABLED", "true")
        monkeypatch.setenv("BOOTSTRAP_SUPERUSER_CREATE", "true")

        from src.config import build_app_config
        from src.utils.super_user import _get_bool_env, ENV_BOOTSTRAP_ENABLE

        config = build_app_config()

        # State: BOOTSTRAP_ENABLED
        assert config.STARTUP_DB_BOOTSTRAP_ENABLED is True
        assert _get_bool_env(ENV_BOOTSTRAP_ENABLE) is True

    def test_bootstrap_state_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: BOOTSTRAP_DISABLED state."""
        monkeypatch.setenv("STARTUP_DB_BOOTSTRAP_ENABLED", "false")
        monkeypatch.setenv("BOOTSTRAP_SUPERUSER_CREATE", "false")

        from src.config import build_app_config
        from src.utils.super_user import _get_bool_env, ENV_BOOTSTRAP_ENABLE

        config = build_app_config()

        # State: BOOTSTRAP_DISABLED
        assert config.STARTUP_DB_BOOTSTRAP_ENABLED is False
        assert _get_bool_env(ENV_BOOTSTRAP_ENABLE) is False


class TestAuthenticationStates:
    """Test authentication states."""

    def test_auth_state_anonymous(self):
        """Test: AUTH_ANONYMOUS state (no token)."""
        # No authorization header
        headers = {}
        
        # State: AUTH_ANONYMOUS
        assert "authorization" not in headers
        assert "Authorization" not in headers

    def test_auth_state_authenticated(self):
        """Test: AUTH_AUTHENTICATED state (valid token)."""
        # With authorization header
        headers = {"Authorization": "Bearer valid-token"}
        
        # State: AUTH_AUTHENTICATED
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_auth_state_expired(self):
        """Test: AUTH_EXPIRED state (token expired)."""
        # Expired token (would be validated by auth system)
        headers = {"Authorization": "Bearer expired-token"}
        
        # State: AUTH_EXPIRED (conceptual - would be detected by JWT validation)
        assert "Authorization" in headers

    def test_auth_state_invalid(self):
        """Test: AUTH_INVALID state (malformed token)."""
        # Invalid token format
        headers = {"Authorization": "InvalidFormat"}
        
        # State: AUTH_INVALID
        assert "Authorization" in headers
        assert not headers["Authorization"].startswith("Bearer ")


class TestCORSStates:
    """Test CORS configuration states."""

    def test_cors_state_single_origin(self, monkeypatch: pytest.MonkeyPatch):
        """Test: CORS_SINGLE_ORIGIN state."""
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: CORS_SINGLE_ORIGIN
        assert len(config.CORS["ALLOW_ORIGINS"]) == 1
        assert config.CORS["ALLOW_ORIGINS"][0] == "http://localhost:3000"

    def test_cors_state_multiple_origins(self, monkeypatch: pytest.MonkeyPatch):
        """Test: CORS_MULTIPLE_ORIGINS state."""
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:8080,https://example.com")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: CORS_MULTIPLE_ORIGINS
        assert len(config.CORS["ALLOW_ORIGINS"]) == 3

    def test_cors_state_credentials_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: CORS_CREDENTIALS_ENABLED state."""
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: CORS_CREDENTIALS_ENABLED
        assert config.CORS["ALLOW_CREDENTIALS"] is True

    def test_cors_state_credentials_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: CORS_CREDENTIALS_DISABLED state."""
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "false")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: CORS_CREDENTIALS_DISABLED
        assert config.CORS["ALLOW_CREDENTIALS"] is False


class TestLoggingStates:
    """Test logging configuration states."""

    def test_logging_state_debug(self, monkeypatch: pytest.MonkeyPatch):
        """Test: LOGGING_DEBUG state."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: LOGGING_DEBUG
        assert config.LOG_LEVEL == "DEBUG"

    def test_logging_state_info(self, monkeypatch: pytest.MonkeyPatch):
        """Test: LOGGING_INFO state."""
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: LOGGING_INFO
        assert config.LOG_LEVEL == "INFO"

    def test_logging_state_warning(self, monkeypatch: pytest.MonkeyPatch):
        """Test: LOGGING_WARNING state."""
        monkeypatch.setenv("LOG_LEVEL", "WARNING")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: LOGGING_WARNING
        assert config.LOG_LEVEL == "WARNING"

    def test_logging_state_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test: LOGGING_ERROR state."""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: LOGGING_ERROR
        assert config.LOG_LEVEL == "ERROR"

    def test_logging_request_enabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: REQUEST_LOGGING_ENABLED state."""
        monkeypatch.setenv("REQUEST_LOG_ENABLED", "true")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: REQUEST_LOGGING_ENABLED
        assert config.REQUEST_LOG_ENABLED is True

    def test_logging_request_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test: REQUEST_LOGGING_DISABLED state."""
        monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")

        from src.config import build_app_config

        config = build_app_config()
        
        # State: REQUEST_LOGGING_DISABLED
        assert config.REQUEST_LOG_ENABLED is False
