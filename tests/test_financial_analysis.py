import asyncio
from datetime import date
from decimal import Decimal

from ashare_agent.domain import (
    FinancialAnalysisType,
    FinancialGrowthStatus,
    FinancialMetric,
    FinancialMetricSeries,
    FinancialSeriesPoint,
    FinancialStatementType,
    FinancialTrendDirection,
    Security,
)
from ashare_agent.services.financial_analysis import FinancialAnalysisService


class StubFinancialSeriesService:
    def __init__(self, series: FinancialMetricSeries) -> None:
        self.series = series

    async def get_financial_series(
        self,
        company: str,
        metric: FinancialMetric,
        *,
        years: int = 5,
        end_year: int | None = None,
    ) -> FinancialMetricSeries:
        assert company == "测试公司"
        assert metric == self.series.metric
        assert years == self.series.requested_years
        assert end_year == self.series.end_year
        return self.series


def _series(values: list[str]) -> FinancialMetricSeries:
    start_year = 2021
    return FinancialMetricSeries(
        security=Security(code="600000", name="测试公司"),
        metric=FinancialMetric.REVENUE,
        label="营业收入",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        requested_years=len(values),
        end_year=start_year + len(values) - 1,
        points=[
            FinancialSeriesPoint(
                report_date=date(start_year + index, 12, 31),
                value=Decimal(value),
                unit="CNY",
            )
            for index, value in enumerate(values)
        ],
    )


def test_financial_analysis_calculates_yoy_cagr_and_trend():
    series = _series(["100", "120", "150"])
    service = FinancialAnalysisService(StubFinancialSeriesService(series))

    result = asyncio.run(
        service.analyze(
            "测试公司",
            [FinancialMetric.REVENUE],
            [
                FinancialAnalysisType.YOY,
                FinancialAnalysisType.CAGR,
                FinancialAnalysisType.TREND,
            ],
            years=3,
            end_year=2023,
        )
    )

    analysis = result.metrics[0]
    assert [point.yoy_rate_percent for point in analysis.growth_points] == [
        None,
        Decimal("20.00"),
        Decimal("25.00"),
    ]
    assert analysis.overall_growth_rate_percent == Decimal("50.00")
    assert analysis.cagr_percent == Decimal("22.47")
    assert analysis.trend_direction == FinancialTrendDirection.CONTINUOUS_GROWTH
    assert analysis.positive_years == 2
    assert analysis.warnings == []


def test_financial_analysis_marks_profit_turnaround_as_non_comparable():
    series = _series(["-10", "5", "-2"])
    service = FinancialAnalysisService(StubFinancialSeriesService(series))

    result = asyncio.run(
        service.analyze(
            "测试公司",
            [FinancialMetric.REVENUE],
            [FinancialAnalysisType.YOY, FinancialAnalysisType.TREND],
            years=3,
            end_year=2023,
        )
    )

    analysis = result.metrics[0]
    assert [point.status for point in analysis.growth_points] == [
        FinancialGrowthStatus.BASELINE,
        FinancialGrowthStatus.TURNAROUND,
        FinancialGrowthStatus.TURNED_TO_LOSS,
    ]
    assert analysis.trend_direction == FinancialTrendDirection.INSUFFICIENT_DATA
    assert analysis.cagr_percent is None
    assert any("扭亏为盈" in warning for warning in analysis.warnings)
    assert any("由盈转亏" in warning for warning in analysis.warnings)
