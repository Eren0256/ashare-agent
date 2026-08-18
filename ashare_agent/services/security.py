import re
from typing import Protocol

from ashare_agent.domain import Security


class SecurityProviderProtocol(Protocol):
    async def list_securities(
        self,
    ) -> list[Security]: ...


class SecurityService:
    def __init__(
        self,
        provider: SecurityProviderProtocol,
    ):
        self._provider = provider

    async def resolve(
        self,
        query: str,
    ) -> Security:

        query = query.strip()

        if not query:
            raise ValueError("Security query cannot be empty")

        securities = await self._provider.list_securities()

        # -------------------------
        # 股票代码直接匹配
        # -------------------------

        code = _normalize_code(query)

        if code:
            for security in securities:
                if security.code == code:
                    return security

            raise ValueError(f"Unknown A-share security code: " f"{query}")

        normalized_query = _normalize_name(query)

        # -------------------------
        # 股票简称精确匹配
        # -------------------------

        exact_matches = [
            security
            for security in securities
            if _normalize_name(security.name) == normalized_query
        ]

        if len(exact_matches) == 1:
            return exact_matches[0]

        # -------------------------
        # 模糊包含匹配
        #
        # 茅台 -> 贵州茅台
        # -------------------------

        partial_matches = [
            security
            for security in securities
            if (normalized_query in _normalize_name(security.name))
            or (_normalize_name(security.name) in normalized_query)
        ]

        if len(partial_matches) == 1:
            return partial_matches[0]

        if not partial_matches:
            raise ValueError(f"Cannot resolve A-share security: " f"{query}")

        names = [f"{item.code} {item.name}" for item in partial_matches[:10]]

        raise ValueError("Ambiguous security name: " f"{query}; candidates={names}")


def _normalize_code(
    value: str,
) -> str | None:

    value = value.strip()

    if re.fullmatch(
        r"\d{6}",
        value,
    ):
        return value

    return None


def _normalize_name(
    value: str,
) -> str:

    value = value.strip().upper()

    # 去掉空白
    value = re.sub(
        r"\s+",
        "",
        value,
    )

    # 用户可能输入：
    # 贵州茅台公司
    # 贵州茅台股份有限公司
    suffixes = (
        "股份有限公司",
        "有限责任公司",
        "有限公司",
        "股份公司",
        "公司",
        "股票",
    )

    for suffix in suffixes:
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break

    return value
