from typing import Protocol

from ashare_agent.domain import (
    Security,
    CompanyBusiness,
)

from .security import (
    SecurityService,
)


class CompanyProviderProtocol(Protocol):
    async def get_business(
        self,
        security: Security,
    ) -> CompanyBusiness: ...


class CompanyService:
    def __init__(
        self,
        security_service: SecurityService,
        company_provider: CompanyProviderProtocol,
    ):
        self._security_service = security_service

        self._company_provider = company_provider

    async def get_business(
        self,
        company: str,
    ) -> CompanyBusiness:

        security = await self._security_service.resolve(company)

        return await self._company_provider.get_business(security)
