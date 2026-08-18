import asyncio
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Protocol

from ashare_agent.domain import (
    CompanyFinancialAnalysis,
    FinancialAnalysisType,
    FinancialGrowthPoint,
    FinancialGrowthStatus,
    FinancialMetric,
    FinancialMetricAnalysis,
    FinancialMetricSeries,
    FinancialSeriesPoint,
    FinancialTrendDirection,
)

_PERCENT_QUANTUM = Decimal("0.01")


class FinancialSeriesServiceProtocol(Protocol):
    async def get_financial_series(
        self,
        company: str,
        metric: FinancialMetric,
        *,
        years: int = 5,
        end_year: int | None = None,
    ) -> FinancialMetricSeries: ...


class FinancialAnalysisService:
    def __init__(
        self,
        financial_service: FinancialSeriesServiceProtocol,
    ):
        self._financial_service = financial_service

    async def analyze(
        self,
        company: str,
        metrics: list[FinancialMetric],
        analyses: list[FinancialAnalysisType],
        *,
        years: int = 5,
        end_year: int | None = None,
    ) -> CompanyFinancialAnalysis:
        if not metrics:
            raise ValueError("At least one financial metric is required")

        if not analyses:
            raise ValueError("At least one financial analysis is required")

        if years < 2 or years > 10:
            raise ValueError("Analysis years must be between 2 and 10")

        unique_metrics = list(dict.fromkeys(metrics))
        unique_analyses = list(dict.fromkeys(analyses))

        series_list = await asyncio.gather(
            *[
                self._financial_service.get_financial_series(
                    company,
                    metric,
                    years=years,
                    end_year=end_year,
                )
                for metric in unique_metrics
            ]
        )

        metric_analyses = [
            _analyze_series(
                series,
                unique_analyses,
            )
            for series in series_list
        ]

        return CompanyFinancialAnalysis(
            security=series_list[0].security,
            analysis_types=unique_analyses,
            metrics=metric_analyses,
        )


def _analyze_series(
    series: FinancialMetricSeries,
    analyses: list[FinancialAnalysisType],
) -> FinancialMetricAnalysis:
    requested = set(analyses)
    needs_growth = bool(
        requested
        & {
            FinancialAnalysisType.YOY,
            FinancialAnalysisType.TREND,
        }
    )
    needs_summary_growth = bool(
        requested
        & {
            FinancialAnalysisType.CAGR,
            FinancialAnalysisType.TREND,
        }
    )

    warnings: list[str] = []

    if len(series.points) < series.requested_years:
        warnings.append(
            f"仅取得 {len(series.points)} 个年度数据，"
            f"少于请求的 {series.requested_years} 个年度。"
        )

    growth_points = _calculate_growth_points(series.points) if needs_growth else []

    if needs_growth:
        warnings.extend(_growth_warnings(growth_points))

    overall_growth_rate = None
    cagr = None

    if needs_summary_growth:
        overall_growth_rate, overall_warning = _calculate_overall_growth(series.points)
        cagr, cagr_warning = _calculate_cagr(series.points)

        if overall_warning:
            warnings.append(overall_warning)

        if cagr_warning:
            warnings.append(cagr_warning)

    valid_rates = [
        point.yoy_rate_percent
        for point in growth_points
        if point.status == FinancialGrowthStatus.AVAILABLE
        and point.yoy_rate_percent is not None
    ]

    positive_years = sum(rate > 0 for rate in valid_rates)
    negative_years = sum(rate < 0 for rate in valid_rates)
    unchanged_years = sum(rate == 0 for rate in valid_rates)

    trend_direction = None

    if FinancialAnalysisType.TREND in requested:
        trend_direction = _classify_trend(
            valid_rates,
            overall_growth_rate,
        )

    return FinancialMetricAnalysis(
        series=series,
        growth_points=growth_points,
        overall_growth_rate_percent=overall_growth_rate,
        cagr_percent=cagr,
        positive_years=positive_years,
        negative_years=negative_years,
        unchanged_years=unchanged_years,
        trend_direction=trend_direction,
        warnings=list(dict.fromkeys(warnings)),
    )


def _calculate_growth_points(
    points: list[FinancialSeriesPoint],
) -> list[FinancialGrowthPoint]:
    if not points:
        return []

    result = [
        FinancialGrowthPoint(
            report_date=points[0].report_date,
            value=points[0].value,
            status=FinancialGrowthStatus.BASELINE,
        )
    ]

    for previous, current in zip(points, points[1:]):
        status = FinancialGrowthStatus.AVAILABLE
        rate = None

        if current.report_date.year - previous.report_date.year != 1:
            status = FinancialGrowthStatus.PERIOD_GAP

        elif previous.value is None or current.value is None:
            status = FinancialGrowthStatus.MISSING_VALUE

        elif previous.value == 0:
            status = FinancialGrowthStatus.ZERO_BASE

        elif previous.value < 0 <= current.value:
            status = FinancialGrowthStatus.TURNAROUND

        elif previous.value >= 0 > current.value:
            status = FinancialGrowthStatus.TURNED_TO_LOSS

        elif previous.value < 0 and current.value < 0:
            status = FinancialGrowthStatus.NEGATIVE_BASE

        else:
            rate = _percentage(
                current.value - previous.value,
                previous.value,
            )

        result.append(
            FinancialGrowthPoint(
                report_date=current.report_date,
                value=current.value,
                previous_report_date=previous.report_date,
                previous_value=previous.value,
                yoy_rate_percent=rate,
                status=status,
            )
        )

    return result


def _calculate_overall_growth(
    points: list[FinancialSeriesPoint],
) -> tuple[Decimal | None, str | None]:
    if len(points) < 2:
        return None, "年度数据不足，无法计算区间累计增长率。"

    first = points[0]
    last = points[-1]

    if first.value is None or last.value is None:
        return None, "区间起点或终点数据缺失，无法计算累计增长率。"

    if first.value <= 0 or last.value < 0:
        return None, "区间起点或终点为非正数，累计增长率不具常规可比意义。"

    return (
        _percentage(
            last.value - first.value,
            first.value,
        ),
        None,
    )


def _calculate_cagr(
    points: list[FinancialSeriesPoint],
) -> tuple[Decimal | None, str | None]:
    if len(points) < 2:
        return None, "年度数据不足，无法计算复合年增长率。"

    first = points[0]
    last = points[-1]
    year_span = last.report_date.year - first.report_date.year

    if year_span <= 0:
        return None, "报告期跨度不足，无法计算复合年增长率。"

    if first.value is None or last.value is None:
        return None, "区间起点或终点数据缺失，无法计算复合年增长率。"

    if first.value <= 0 or last.value <= 0:
        return None, "区间起点或终点为非正数，复合年增长率不具常规意义。"

    with localcontext() as context:
        context.prec = 40
        rate = (
            (last.value / first.value) ** (Decimal(1) / Decimal(year_span)) - Decimal(1)
        ) * Decimal(100)

    return _round_percent(rate), None


def _classify_trend(
    valid_rates: list[Decimal],
    overall_growth_rate: Decimal | None,
) -> FinancialTrendDirection:
    if not valid_rates:
        return FinancialTrendDirection.INSUFFICIENT_DATA

    if all(rate > 0 for rate in valid_rates):
        return FinancialTrendDirection.CONTINUOUS_GROWTH

    if all(rate < 0 for rate in valid_rates):
        return FinancialTrendDirection.CONTINUOUS_DECLINE

    if all(rate == 0 for rate in valid_rates):
        return FinancialTrendDirection.STABLE

    if overall_growth_rate is None:
        return FinancialTrendDirection.MIXED

    if overall_growth_rate > 0:
        return FinancialTrendDirection.VOLATILE_GROWTH

    if overall_growth_rate < 0:
        return FinancialTrendDirection.VOLATILE_DECLINE

    return FinancialTrendDirection.MIXED


def _growth_warnings(
    points: list[FinancialGrowthPoint],
) -> list[str]:
    messages = {
        FinancialGrowthStatus.MISSING_VALUE: (
            "部分年度数据缺失，对应同比增长率未计算。"
        ),
        FinancialGrowthStatus.PERIOD_GAP: (
            "年度序列存在间隔，跨期数据未作为同比增长率计算。"
        ),
        FinancialGrowthStatus.ZERO_BASE: ("部分年度的上期值为零，对应增长率无法计算。"),
        FinancialGrowthStatus.NEGATIVE_BASE: (
            "部分年度以上期负数为基数，普通增长率不具常规意义。"
        ),
        FinancialGrowthStatus.TURNAROUND: (
            "序列中存在由负转正，应按扭亏为盈理解，不计算普通增长率。"
        ),
        FinancialGrowthStatus.TURNED_TO_LOSS: (
            "序列中存在由正转负，应按由盈转亏理解，不计算普通增长率。"
        ),
    }

    statuses = {point.status for point in points}

    return [message for status, message in messages.items() if status in statuses]


def _percentage(
    numerator: Decimal,
    denominator: Decimal,
) -> Decimal:
    return _round_percent(numerator / denominator * Decimal(100))


def _round_percent(
    value: Decimal,
) -> Decimal:
    return value.quantize(
        _PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
