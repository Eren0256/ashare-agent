import logging
from typing import Protocol

from ashare_agent.cache import CacheStore
from ashare_agent.domain import Security

logger = logging.getLogger(__name__)

SECURITY_LIST_CACHE_KEY = "akshare:stock_info_a_code_name:v1"


class SecurityProviderProtocol(Protocol):
    async def list_securities(
        self,
    ) -> list[Security]: ...


class CachedSecurityProvider:
    def __init__(
        self,
        provider: SecurityProviderProtocol,
        cache: CacheStore,
        *,
        ttl_seconds: float,
    ):
        self._provider = provider
        self._cache = cache
        self._ttl_seconds = ttl_seconds

    async def list_securities(
        self,
    ) -> list[Security]:
        cached = await self._load_cached()

        if cached is not None:
            return cached

        async with self._cache.lock(SECURITY_LIST_CACHE_KEY):
            # Double-check after taking the lock so concurrent cache misses
            # only trigger one AkShare request across all workers.
            cached = await self._load_cached()

            if cached is not None:
                return cached

            securities = await self._provider.list_securities()

            await self._store_cached(
                [security.model_dump(mode="json") for security in securities]
            )

            return securities

    async def _load_cached(
        self,
    ) -> list[Security] | None:
        try:
            value = await self._cache.get(SECURITY_LIST_CACHE_KEY)
        except Exception:
            logger.warning(
                "Failed to read the security list cache",
                exc_info=True,
            )
            return None

        if value is None:
            return None

        try:
            if not isinstance(value, list) or not value:
                raise ValueError("Cached security list is invalid")

            return [Security.model_validate(item) for item in value]
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid cached security list",
                exc_info=True,
            )
            await self._delete_cached()
            return None

    async def _store_cached(
        self,
        value,
    ) -> None:
        try:
            await self._cache.set(
                SECURITY_LIST_CACHE_KEY,
                value,
                ttl_seconds=self._ttl_seconds,
            )
        except Exception:
            # A cache failure must not turn a successful provider request
            # into a failed business request.
            logger.warning(
                "Failed to write the security list cache",
                exc_info=True,
            )

    async def _delete_cached(self) -> None:
        try:
            await self._cache.delete(SECURITY_LIST_CACHE_KEY)
        except Exception:
            logger.warning(
                "Failed to delete the invalid security list cache",
                exc_info=True,
            )
