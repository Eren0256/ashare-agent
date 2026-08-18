from decimal import Decimal

from ashare_agent.domain import (
    ChartAxis,
    ChartSeries,
    ChartSeriesStyle,
    ChartSpec,
    ChartType,
    CompanyFinancialAnalysis,
    FinancialMetricAnalysis,
)

_TREND_LABELS = {
    "continuous_growth": "连续增长",
    "continuous_decline": "连续下降",
    "volatile_growth": "波动增长",
    "volatile_decline": "波动下降",
    "stable": "基本稳定",
    "mixed": "涨跌交替",
    "insufficient_data": "数据不足",
}


class FinancialChartService:
    def build_specs(
        self,
        analysis: CompanyFinancialAnalysis,
    ) -> list[ChartSpec]:
        return [
            self._build_metric_spec(
                analysis,
                metric_analysis,
            )
            for metric_analysis in analysis.metrics
        ]

    def _build_metric_spec(
        self,
        analysis: CompanyFinancialAnalysis,
        metric_analysis: FinancialMetricAnalysis,
    ) -> ChartSpec:
        series = metric_analysis.series
        x_labels = [str(point.report_date.year) for point in series.points]
        value_values, value_unit = _chart_values(metric_analysis)
        value_series = ChartSeries(
            name=series.label,
            values=value_values,
            unit=value_unit,
            style=ChartSeriesStyle.BAR,
            axis=ChartAxis.LEFT,
        )

        chart_series = [value_series]
        right_y_label = None
        chart_type = ChartType.BAR

        growth_by_year = {
            point.report_date.year: point.yoy_rate_percent
            for point in metric_analysis.growth_points
        }

        if metric_analysis.growth_points:
            chart_series.append(
                ChartSeries(
                    name="同比增长率",
                    values=[growth_by_year.get(int(year)) for year in x_labels],
                    unit="%",
                    style=ChartSeriesStyle.LINE,
                    axis=ChartAxis.RIGHT,
                )
            )
            chart_type = ChartType.COMBO
            right_y_label = "同比增长率（%）"

        notes = _analysis_notes(metric_analysis)
        notes.extend(metric_analysis.warnings)

        return ChartSpec(
            chart_type=chart_type,
            title=(
                f"{analysis.security.name}近"
                f"{len(series.points)}年{series.label}趋势"
            ),
            x_labels=x_labels,
            series=chart_series,
            left_y_label=f"{series.label}（{value_unit}）",
            right_y_label=right_y_label,
            notes=notes,
        )


def _chart_values(
    analysis: FinancialMetricAnalysis,
) -> tuple[list[Decimal | None], str]:
    units = {
        point.display_unit
        for point in analysis.series.points
        if point.display_unit is not None
    }

    if len(units) == 1:
        return (
            [point.display_value for point in analysis.series.points],
            next(iter(units)),
        )

    return (
        [point.value for point in analysis.series.points],
        analysis.series.points[0].unit,
    )


def _analysis_notes(
    analysis: FinancialMetricAnalysis,
) -> list[str]:
    notes: list[str] = []

    if analysis.overall_growth_rate_percent is not None:
        notes.append(
            "区间累计增长率："
            f"{_format_decimal(analysis.overall_growth_rate_percent)}%"
        )

    if analysis.cagr_percent is not None:
        notes.append(
            "复合年增长率（CAGR）：" f"{_format_decimal(analysis.cagr_percent)}%"
        )

    if analysis.trend_direction is not None:
        notes.append("趋势：" + _TREND_LABELS[analysis.trend_direction.value])

    return notes


def _format_decimal(
    value: Decimal,
) -> str:
    return format(value, "f")
