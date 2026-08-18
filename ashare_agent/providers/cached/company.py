import asyncio
import logging
from typing import Protocol

from ashare_agent.cache import CacheStore
from ashare_agent.domain import (
    CompanyBusiness,
    Security,
)

logger = logging.getLogger(__name__)

COMPANY_BUSINESS_CACHE_KEY_PREFIX = "akshare:stock_zyjs_ths:v1"


class CompanyProviderProtocol(Protocol):
    async def get_business(
        self,
        security: Security,
    ) -> CompanyBusiness: ...


class CachedCompanyProvider:
    def __init__(
        self,
        provider: CompanyProviderProtocol,
        cache: CacheStore,
        *,
        ttl_seconds: float,
    ):
        self._provider = provider
        self._cache = cache
        self._ttl_seconds = ttl_seconds
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    async def get_business(
        self,
        security: Security,
    ) -> CompanyBusiness:
        key = _business_cache_key(security.code)
        cached = await self._load_cached(key, security.code)

        if cached is not None:
            return cached

        refresh_lock = self._refresh_locks.setdefault(
            key,
            asyncio.Lock(),
        )

        async with refresh_lock:
            cached = await self._load_cached(key, security.code)

            if cached is not None:
                return cached

            business = await self._provider.get_business(security)

            await self._store_cached(
                key,
                business.model_dump(mode="json"),
            )

            return business

    async def _load_cached(
        self,
        key: str,
        expected_code: str,
    ) -> CompanyBusiness | None:
        try:
            value = await self._cache.get(key)
        except Exception:
            logger.warning(
                "Failed to read the company business cache",
                exc_info=True,
            )
            return None

        if value is None:
            return None

        try:
            business = CompanyBusiness.model_validate(value)

            if business.security.code != expected_code:
                raise ValueError("Cached company business code does not match")

            return business
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid cached company business data",
                exc_info=True,
            )
            await self._delete_cached(key)
            return None

    async def _store_cached(
        self,
        key: str,
        value,
    ) -> None:
        try:
            await self._cache.set(
                key,
                value,
                ttl_seconds=self._ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Failed to write the company business cache",
                exc_info=True,
            )

    async def _delete_cached(
        self,
        key: str,
    ) -> None:
        try:
            await self._cache.delete(key)
        except Exception:
            logger.warning(
                "Failed to delete invalid company business cache",
                exc_info=True,
            )


def _business_cache_key(
    security_code: str,
) -> str:
    return f"{COMPANY_BUSINESS_CACHE_KEY_PREFIX}:{security_code}"
