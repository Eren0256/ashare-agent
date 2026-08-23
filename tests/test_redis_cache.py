import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from ashare_agent.cache import RedisCacheStore
from ashare_agent.domain import Security
from ashare_agent.providers import CachedSecurityProvider
from ashare_agent.providers.cached.security import SECURITY_LIST_CACHE_KEY

REDIS_TEST_URL = os.getenv("REDIS_TEST_URL")


class SlowSecurityProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def list_securities(self) -> list[Security]:
        self.calls += 1
        await asyncio.sleep(0.05)
        return [Security(code="002594", name="比亚迪")]


@pytest.mark.skipif(
    not REDIS_TEST_URL,
    reason="set REDIS_TEST_URL to run the Redis integration test",
)
def test_redis_cache_is_shared_and_refreshes_only_once_across_workers():
    async def scenario() -> None:
        prefix = f"ashare-agent:test-cache:{uuid4().hex}"
        caches = [
            RedisCacheStore(
                REDIS_TEST_URL or "",
                key_prefix=prefix,
                lock_ttl_seconds=5,
                lock_wait_timeout_seconds=2,
                lock_poll_interval_seconds=0.01,
            )
            for _ in range(2)
        ]
        cleanup = Redis.from_url(REDIS_TEST_URL or "", decode_responses=True)
        upstream = SlowSecurityProvider()
        providers = [
            CachedSecurityProvider(upstream, cache, ttl_seconds=60)
            for cache in caches
        ]

        try:
            results = await asyncio.gather(
                *(provider.list_securities() for provider in providers)
            )

            assert results == [
                [Security(code="002594", name="比亚迪")],
                [Security(code="002594", name="比亚迪")],
            ]
            assert upstream.calls == 1
            assert await caches[1].get(SECURITY_LIST_CACHE_KEY) == [
                {"code": "002594", "name": "比亚迪"}
            ]
        finally:
            keys = [key async for key in cleanup.scan_iter(f"{prefix}:*")]
            if keys:
                await cleanup.delete(*keys)
            await asyncio.gather(*(cache.close() for cache in caches))
            await cleanup.aclose()

    asyncio.run(scenario())
