import asyncio

import pytest

from ashare_agent.domain import Security
from ashare_agent.services.security import SecurityService


class StubSecurityProvider:
    async def list_securities(self) -> list[Security]:
        return [
            Security(code="600519", name="贵州茅台"),
            Security(code="600000", name="浦发银行"),
            Security(code="601398", name="工商银行"),
        ]


def test_security_service_resolves_code_and_normalized_company_name():
    service = SecurityService(StubSecurityProvider())

    by_code = asyncio.run(service.resolve("600519"))
    by_name = asyncio.run(service.resolve("贵州茅台股份有限公司"))

    assert by_code == Security(code="600519", name="贵州茅台")
    assert by_name == by_code


def test_security_service_rejects_ambiguous_partial_name():
    service = SecurityService(StubSecurityProvider())

    with pytest.raises(ValueError, match="Ambiguous security name"):
        asyncio.run(service.resolve("银行"))
