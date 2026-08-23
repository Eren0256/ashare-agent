import asyncio
from contextlib import asynccontextmanager
import json
import logging
import math
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisCacheStore:
    def __init__(
        self,
        url: str,
        *,
        key_prefix: str = "ashare-agent:cache",
        lock_ttl_seconds: float = 300,
        lock_wait_timeout_seconds: float = 300,
        lock_poll_interval_seconds: float = 0.1,
    ) -> None:
        if lock_ttl_seconds <= 0:
            raise ValueError("lock_ttl_seconds must be positive")
        if lock_wait_timeout_seconds <= 0:
            raise ValueError("lock_wait_timeout_seconds must be positive")
        if lock_poll_interval_seconds <= 0:
            raise ValueError("lock_poll_interval_seconds must be positive")
        self._client = Redis.from_url(url, decode_responses=True)
        self._key_prefix = key_prefix.strip(":")
        self._lock_ttl_ms = math.ceil(lock_ttl_seconds * 1_000)
        self._lock_wait_timeout_seconds = lock_wait_timeout_seconds
        self._lock_poll_interval_seconds = lock_poll_interval_seconds
        self._fallback_locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> Any | None:
        cache_key = self._cache_key(key)
        payload = await self._client.get(cache_key)
        if payload is None:
            return None
        try:
            return json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            await self._client.delete(cache_key)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: float,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Cache TTL must be greater than zero")
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await self._client.set(
            self._cache_key(key),
            payload,
            px=math.ceil(ttl_seconds * 1_000),
        )

    async def delete(self, key: str) -> None:
        await self._client.delete(self._cache_key(key))

    @asynccontextmanager
    async def lock(self, key: str):
        lock_key = self._lock_key(key)
        token = uuid4().hex
        try:
            acquired = await self._acquire_lock(lock_key, token)
        except RedisError:
            logger.warning(
                "Redis lock is unavailable; using a process-local fallback",
                exc_info=True,
            )
            acquired = False

        if not acquired:
            fallback = self._fallback_locks.setdefault(key, asyncio.Lock())
            async with fallback:
                yield
            return

        try:
            yield
        finally:
            try:
                await self._client.eval(
                    _RELEASE_LOCK_SCRIPT,
                    1,
                    lock_key,
                    token,
                )
            except RedisError:
                logger.warning("Failed to release Redis cache lock", exc_info=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def _acquire_lock(self, lock_key: str, token: str) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._lock_wait_timeout_seconds
        while True:
            acquired = await self._client.set(
                lock_key,
                token,
                nx=True,
                px=self._lock_ttl_ms,
            )
            if acquired:
                return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning("Timed out waiting for Redis cache lock %s", lock_key)
                return False
            await asyncio.sleep(min(self._lock_poll_interval_seconds, remaining))

    def _cache_key(self, key: str) -> str:
        return f"{self._key_prefix}:value:{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self._key_prefix}:lock:{key}"
