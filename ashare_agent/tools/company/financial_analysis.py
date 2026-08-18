from typing import Any, Protocol

from pydantic import BaseModel, Field

from ashare_agent.domain import (
    ChartArtifact,
    CompanyFinancialAnalysis,
    FinancialAnalysisType,
    FinancialMetric,
    ResponseOutputMode,
)

from ..base import BaseTool


class FinancialAnalysisServiceProtocol(Protocol):
    async def analyze(
        self,
        company: str,
        metrics: list[FinancialMetric],
        analyses: list[FinancialAnalysisType],
        *,
        years: int = 5,
        end_year: int | None = None,
    ) -> Any: ...


class FinancialChartServiceProtocol(Protocol):
    def build_specs(self, analysis) -> list[Any]: ...


class ChartRendererProtocol(Protocol):
    async def render(self, spec) -> Any: ...


class AnalyzeCompanyFinancialsResult(BaseModel):
    """财务分析 Tool 的应用层返回结果。"""

    analysis: CompanyFinancialAnalysis
    artifacts: list[ChartArtifact] = Field(default_factory=list)


class AnalyzeCompanyFinancialsArgs(BaseModel):
    company: str = Field(
        description=("公司名称、股票简称或者股票代码，例如贵州茅台、600519")
    )

    metrics: list[FinancialMetric] = Field(
        min_length=1,
        max_length=3,
        description=(
            "只选择用户明确询问的财务指标，不要添加未询问的指标。"
            "指标枚举与基础财务数据工具相同。"
        ),
    )

    analyses: list[FinancialAnalysisType] = Field(
        min_length=1,
        description=(
            "分析类型：values=年度原始数值序列；yoy=逐年同比增长率；"
            "cagr=区间累计增长率和复合年增长率；"
            "trend=数值、同比、CAGR及趋势特征。"
            "用户只问近N年数值时选择values；只问同比时选择yoy；"
            "笼统询问增长率时同时选择yoy和cagr；询问趋势时选择trend。"
        ),
    )

    years: int = Field(
        default=5,
        ge=2,
        le=10,
        description=("需要几个年度报告的数据。近5年表示5个年度数值和4个同比区间。"),
    )

    end_year: int | None = Field(
        default=None,
        ge=1990,
        le=2100,
        description=("用户明确指定的截止年度；省略时使用最新已披露的完整年报。"),
    )

    output_modes: list[ResponseOutputMode] = Field(
        default_factory=lambda: [ResponseOutputMode.TEXT],
        min_length=1,
        description=(
            "输出形式：text=文字回答，chart=生成图表。"
            "只有用户明确要求绘图、图表或可视化时才添加chart。"
        ),
    )


class AnalyzeCompanyFinancialsTool(BaseTool):
    name = "analyze_company_financials"

    description = (
        "查询一家中国A股上市公司最近若干完整年度的财务指标序列，"
        "并以确定性代码计算逐年同比、区间累计增长率、CAGR和趋势特征。"
        "适用于近N年、历年变化、增长率、复合增速和增长趋势问题；"
        "不用于单个报告期基础数值查询、预测或原因分析。"
    )

    intents = ("financial_analysis",)

    keywords = (
        "过去",
        "历年",
        "历史",
        "增长",
        "增速",
        "同比",
        "复合增长",
        "CAGR",
        "年均",
        "趋势",
        "变化",
    )

    args_model = AnalyzeCompanyFinancialsArgs

    def __init__(
        self,
        financial_analysis_service: FinancialAnalysisServiceProtocol,
        chart_service: FinancialChartServiceProtocol | None = None,
        chart_renderer: ChartRendererProtocol | None = None,
    ):
        self._financial_analysis_service = financial_analysis_service
        self._chart_service = chart_service
        self._chart_renderer = chart_renderer

    async def run(
        self,
        args: AnalyzeCompanyFinancialsArgs,
    ) -> Any:
        analysis = await self._financial_analysis_service.analyze(
            company=args.company,
            metrics=args.metrics,
            analyses=args.analyses,
            years=args.years,
            end_year=args.end_year,
        )

        artifacts = []

        if ResponseOutputMode.CHART in args.output_modes:
            if self._chart_service is None or self._chart_renderer is None:
                raise RuntimeError("Chart rendering is not configured")

            specs = self._chart_service.build_specs(analysis)

            for spec in specs:
                artifacts.append(await self._chart_renderer.render(spec))

        return AnalyzeCompanyFinancialsResult(
            analysis=analysis,
            artifacts=artifacts,
        )
