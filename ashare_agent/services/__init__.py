from .security import (
    SecurityService,
)

from .company import (
    CompanyService,
)

from .financial import (
    FinancialService,
)

from .financial_analysis import (
    FinancialAnalysisService,
)


def create_default_security_service() -> SecurityService:
    settings, cache = _create_default_dependencies()
    return _create_security_service(cache, settings)


def create_default_company_service() -> CompanyService:

    from ashare_agent.providers import (
        AkshareCompanyProvider,
        CachedCompanyProvider,
    )

    settings, cache = _create_default_dependencies()
    security_service = _create_security_service(cache, settings)

    company_provider = CachedCompanyProvider(
        AkshareCompanyProvider(),
        cache,
        ttl_seconds=(settings.company_business_cache_ttl_seconds),
    )

    return CompanyService(
        security_service=security_service,
        company_provider=company_provider,
    )


def _create_default_dependencies():
    from ashare_agent.cache import SqliteCacheStore
    from ashare_agent.config import get_settings

    settings = get_settings()
    cache = SqliteCacheStore(settings.cache_db_path)
    return settings, cache


def _create_security_service(cache, settings) -> SecurityService:
    from ashare_agent.providers import (
        AkshareSecurityProvider,
        CachedSecurityProvider,
    )

    provider = CachedSecurityProvider(
        AkshareSecurityProvider(),
        cache,
        ttl_seconds=settings.security_list_cache_ttl_seconds,
    )
    return SecurityService(provider)


def create_default_financial_service() -> FinancialService:

    from ashare_agent.providers import (
        AkshareFinancialReportProvider,
        CachedFinancialReportProvider,
    )

    settings, cache = _create_default_dependencies()
    security_service = _create_security_service(cache, settings)

    financial_provider = CachedFinancialReportProvider(
        AkshareFinancialReportProvider(),
        cache,
        ttl_seconds=(settings.financial_report_cache_ttl_seconds),
    )

    return FinancialService(
        security_service=security_service,
        financial_provider=financial_provider,
    )


def create_default_financial_analysis_service() -> FinancialAnalysisService:
    return FinancialAnalysisService(create_default_financial_service())


__all__ = [
    "SecurityService",
    "CompanyService",
    "FinancialService",
    "FinancialAnalysisService",
    "create_default_security_service",
    "create_default_company_service",
    "create_default_financial_service",
    "create_default_financial_analysis_service",
]
