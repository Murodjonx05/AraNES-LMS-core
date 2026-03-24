from __future__ import annotations

import asyncio

import pytest

from src.utils.cache import RedisCacheService, resolve_heartbeat_delay


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.raise_on_get = False
        self.raise_on_ping = False
        self.deleted: list[str] = []
        self.close_calls = 0
        self.ping_calls = 0

    async def get(self, key: str):
        if self.raise_on_get:
            raise RuntimeError("redis down")
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int):
        self.values[key] = value

    async def delete(self, key: str):
        self.deleted.append(key)
        self.values.pop(key, None)

    async def ping(self):
        self.ping_calls += 1
        if self.raise_on_ping:
            raise RuntimeError("ping failed")
        return True

    async def aclose(self):
        self.close_calls += 1
        return None


def test_resolve_heartbeat_delay_caps_at_last_value():
    schedule = (60, 600, 1200)
    assert resolve_heartbeat_delay(schedule, 0) == 60
    assert resolve_heartbeat_delay(schedule, 1) == 60
    assert resolve_heartbeat_delay(schedule, 2) == 600
    assert resolve_heartbeat_delay(schedule, 3) == 1200
    assert resolve_heartbeat_delay(schedule, 7) == 1200


@pytest.mark.asyncio
async def test_cache_hit_returns_deserialized_payload():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=False,
        heartbeat_schedule_seconds=(60,),
    )
    fake = _FakeRedis()
    fake.values["cache:key"] = '{"data":{"en":"Hello"},"key":"hello"}'
    service.enabled = True
    service.client = fake
    service._available = True

    payload = await service.get_json("cache:key")

    assert payload == {"key": "hello", "data": {"en": "Hello"}}


@pytest.mark.asyncio
async def test_cache_get_exception_marks_service_unavailable():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=False,
        heartbeat_schedule_seconds=(60,),
    )
    fake = _FakeRedis()
    fake.raise_on_get = True
    service.enabled = True
    service.client = fake
    service._available = True

    payload = await service.get_json("cache:key")

    assert payload is None
    assert service.is_available() is False


@pytest.mark.asyncio
async def test_malformed_cached_json_is_treated_as_cache_miss_and_deleted():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=False,
        heartbeat_schedule_seconds=(60,),
    )
    fake = _FakeRedis()
    fake.values["cache:key"] = "{not-valid-json"
    service.enabled = True
    service.client = fake
    service._available = True

    payload = await service.get_json("cache:key")

    assert payload is None
    assert fake.deleted == ["cache:key"]
    assert service.is_available() is True


@pytest.mark.asyncio
async def test_close_clears_client_and_availability():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=False,
        heartbeat_schedule_seconds=(60,),
    )
    fake = _FakeRedis()
    service.enabled = True
    service.client = fake
    service._available = True

    await service.close()

    assert fake.close_calls == 1
    assert service.client is None
    assert service.is_available() is False


@pytest.mark.asyncio
async def test_start_heartbeat_does_not_restart_after_close():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=True,
        heartbeat_schedule_seconds=(60,),
    )
    fake = _FakeRedis()
    service.enabled = True
    service.client = fake
    service._available = True

    await service.close()
    await service.start_heartbeat()

    assert service._heartbeat_task is None
    assert fake.close_calls == 1


@pytest.mark.asyncio
async def test_heartbeat_loop_honors_initial_delay_before_first_ping():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=True,
        heartbeat_schedule_seconds=(60,),
    )
    fake = _FakeRedis()
    service.enabled = True
    service.client = fake
    service._available = False
    sleep_calls: list[float] = []

    async def _sleep(delay: float):
        sleep_calls.append(delay)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.utils.cache.asyncio.sleep", _sleep)
            await service.heartbeat_loop(initial_delay_seconds=15)

    assert sleep_calls == [15]
    assert fake.ping_calls == 0


@pytest.mark.asyncio
async def test_ping_times_out_and_marks_service_unavailable():
    service = RedisCacheService(
        enabled=True,
        redis_url="redis://unused",
        default_ttl_seconds=3600,
        heartbeat_enabled=True,
        heartbeat_schedule_seconds=(60,),
        command_timeout_seconds=0.01,
    )

    class _HangingRedis(_FakeRedis):
        async def ping(self):
            self.ping_calls += 1
            await asyncio.sleep(3600)

    fake = _HangingRedis()
    service.enabled = True
    service.client = fake
    service._available = True

    ok = await service.ping()

    assert ok is False
    assert service.is_available() is False
    assert fake.ping_calls == 1
