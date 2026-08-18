import asyncio
import logging
from typing import Protocol

from ashare_agent.cache import CacheStore
from ashare_agent.domain import (
    FinancialStatement,
    FinancialStatementType,
    Security,
)

logger = logging.getLogger(__name__)

FINANCIAL_REPORT_CACHE_KEY_PREFIX = "akshare:stock_financial_report_sina:v2"


class FinancialReportProviderProtocol(Protocol):
    async def get_statement(
        self,
        security: Security,
        statement_type: FinancialStatementType,
    ) -> FinancialStatement: ...


class CachedFinancialReportProvider:
    def __init__(
        self,
        provider: FinancialReportProviderProtocol,
        cache: CacheStore,
        *,
        ttl_seconds: float,
    ):
        self._provider = provider
        self._cache = cache
        self._ttl_seconds = ttl_seconds
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    async def get_statement(
        self,
        security: Security,
        statement_type: FinancialStatementType,
    ) -> FinancialStatement:
        key = _financial_report_cache_key(
            security.code,
            statement_type,
        )
        cached = await self._load_cached(
            key,
            security.code,
            statement_type,
        )

        if cached is not None:
            return cached

        refresh_lock = self._refresh_locks.setdefault(
            key,
            asyncio.Lock(),
        )

        async with refresh_lock:
            cached = await self._load_cached(
                key,
                security.code,
                statement_type,
            )

            if cached is not None:
                return cached

            statement = await self._provider.get_statement(
                security,
                statement_type,
            )

            await self._store_cached(
                key,
                statement.model_dump(mode="json"),
            )

            return statement

    async def _load_cached(
        self,
        key: str,
        expected_code: str,
        expected_type: FinancialStatementType,
    ) -> FinancialStatement | None:
        try:
            value = await self._cache.get(key)
        except Exception:
            logger.warning(
                "Failed to read the financial report cache",
                exc_info=True,
            )
            return None

        if value is None:
            return None

        try:
            statement = FinancialStatement.model_validate(value)

            if statement.security.code != expected_code:
                raise ValueError("Cached financial report code does not match")

            if statement.statement_type != expected_type:
                raise ValueError("Cached financial report type does not match")

            if not statement.periods:
                raise ValueError("Cached financial report has no periods")

            return statement
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid cached financial report",
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
                "Failed to write the financial report cache",
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
                "Failed to delete the invalid financial report cache",
                exc_info=True,
            )


def _financial_report_cache_key(
    security_code: str,
    statement_type: FinancialStatementType,
) -> str:
    return (
        f"{FINANCIAL_REPORT_CACHE_KEY_PREFIX}:"
        f"{security_code}:{statement_type.value}"
    )
