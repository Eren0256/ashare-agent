from .base import BaseTool

from .models import (
    ToolCall,
    ToolResult,
    ToolSpec,
)

from .registry import ToolRegistry

from .selector import ToolSelector

from .company import (
    AnalyzeCompanyFinancialsResult,
    AnalyzeCompanyFinancialsTool,
    GetCompanyBusinessTool,
    GetCompanyFinancialDataTool,
)


def create_default_tool_registry() -> ToolRegistry:
    """
    创建默认工具池。
    """

    # 延迟 import，避免 tools 层加载时
    # 立即初始化所有 service/provider
    from ashare_agent.services import (
        FinancialAnalysisService,
        create_default_company_service,
        create_default_financial_service,
    )

    from ashare_agent.config import get_settings

    from ashare_agent.visualization import (
        FinancialChartService,
        MatplotlibChartRenderer,
    )

    registry = ToolRegistry()

    company_service = create_default_company_service()
    financial_service = create_default_financial_service()
    financial_analysis_service = FinancialAnalysisService(financial_service)
    settings = get_settings()
    chart_service = FinancialChartService()
    chart_renderer = MatplotlibChartRenderer(
        settings.chart_artifact_dir,
        font_family=settings.chart_font_family,
    )

    registry.register(GetCompanyBusinessTool(company_service))
    registry.register(GetCompanyFinancialDataTool(financial_service))
    registry.register(
        AnalyzeCompanyFinancialsTool(
            financial_analysis_service,
            chart_service,
            chart_renderer,
        )
    )

    return registry


def create_default_tool_selector(
    registry: ToolRegistry,
) -> ToolSelector:

    return ToolSelector(registry)


__all__ = [
    "BaseTool",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "ToolRegistry",
    "ToolSelector",
    "GetCompanyBusinessTool",
    "GetCompanyFinancialDataTool",
    "AnalyzeCompanyFinancialsResult",
    "AnalyzeCompanyFinancialsTool",
    "create_default_tool_registry",
    "create_default_tool_selector",
]
