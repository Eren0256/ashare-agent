import asyncio
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from ashare_agent.domain import (
    CompanyFinancialData,
    FinancialMetric,
    FinancialMetricSeries,
    FinancialMetricValue,
    FinancialSeriesPoint,
    FinancialStatement,
    FinancialStatementPeriod,
    FinancialStatementType,
    Security,
)

from .security import SecurityService


class FinancialReportProviderProtocol(Protocol):
    async def get_statement(
        self,
        security: Security,
        statement_type: FinancialStatementType,
    ) -> FinancialStatement: ...


@dataclass(frozen=True)
class MetricDefinition:
    label: str
    statement_type: FinancialStatementType
    source_fields: tuple[str, ...]
    unit: str = "CNY"


METRIC_DEFINITIONS = {
    # 资产负债表
    FinancialMetric.CASH: MetricDefinition(
        label="货币资金",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("货币资金",),
    ),
    FinancialMetric.ACCOUNTS_RECEIVABLE: MetricDefinition(
        label="应收账款",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("应收账款",),
    ),
    FinancialMetric.INVENTORY: MetricDefinition(
        label="存货",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("存货",),
    ),
    FinancialMetric.CURRENT_ASSETS: MetricDefinition(
        label="流动资产合计",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("流动资产合计",),
    ),
    FinancialMetric.TOTAL_ASSETS: MetricDefinition(
        label="资产总计",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("资产总计",),
    ),
    FinancialMetric.CURRENT_LIABILITIES: MetricDefinition(
        label="流动负债合计",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("流动负债合计",),
    ),
    FinancialMetric.TOTAL_LIABILITIES: MetricDefinition(
        label="负债合计",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=("负债合计",),
    ),
    FinancialMetric.PARENT_EQUITY: MetricDefinition(
        label="归属于母公司股东权益合计",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=(
            "归属于母公司股东权益合计",
            "归属于母公司所有者权益合计",
        ),
    ),
    FinancialMetric.TOTAL_EQUITY: MetricDefinition(
        label="所有者权益合计",
        statement_type=FinancialStatementType.BALANCE_SHEET,
        source_fields=(
            "所有者权益(或股东权益)合计",
            "所有者权益合计",
        ),
    ),
    # 利润表
    FinancialMetric.REVENUE: MetricDefinition(
        label="营业收入",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("营业收入",),
    ),
    FinancialMetric.TOTAL_REVENUE: MetricDefinition(
        label="营业总收入",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("营业总收入",),
    ),
    FinancialMetric.OPERATING_COST: MetricDefinition(
        label="营业成本",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("营业成本",),
    ),
    FinancialMetric.OPERATING_PROFIT: MetricDefinition(
        label="营业利润",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("营业利润",),
    ),
    FinancialMetric.TOTAL_PROFIT: MetricDefinition(
        label="利润总额",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("利润总额",),
    ),
    FinancialMetric.NET_PROFIT: MetricDefinition(
        label="净利润",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("净利润",),
    ),
    FinancialMetric.PARENT_NET_PROFIT: MetricDefinition(
        label="归属于母公司所有者的净利润",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=(
            "归属于母公司所有者的净利润",
            "归属于母公司股东的净利润",
        ),
    ),
    FinancialMetric.BASIC_EPS: MetricDefinition(
        label="基本每股收益",
        statement_type=FinancialStatementType.INCOME_STATEMENT,
        source_fields=("基本每股收益",),
        unit="CNY/share",
    ),
    # 现金流量表
    FinancialMetric.OPERATING_CASH_FLOW: MetricDefinition(
        label="经营活动产生的现金流量净额",
        statement_type=FinancialStatementType.CASH_FLOW_STATEMENT,
        source_fields=("经营活动产生的现金流量净额",),
    ),
    FinancialMetric.INVESTING_CASH_FLOW: MetricDefinition(
        label="投资活动产生的现金流量净额",
        statement_type=FinancialStatementType.CASH_FLOW_STATEMENT,
        source_fields=("投资活动产生的现金流量净额",),
    ),
    FinancialMetric.FINANCING_CASH_FLOW: MetricDefinition(
        label="筹资活动产生的现金流量净额",
        statement_type=FinancialStatementType.CASH_FLOW_STATEMENT,
        source_fields=("筹资活动产生的现金流量净额",),
    ),
    FinancialMetric.NET_CASH_INCREASE: MetricDefinition(
        label="现金及现金等价物净增加额",
        statement_type=FinancialStatementType.CASH_FLOW_STATEMENT,
        source_fields=("现金及现金等价物净增加额",),
    ),
    FinancialMetric.ENDING_CASH_EQUIVALENTS: MetricDefinition(
        label="期末现金及现金等价物余额",
        statement_type=FinancialStatementType.CASH_FLOW_STATEMENT,
        source_fields=(
            "期末现金及现金等价物余额",
            "现金的期末余额",
        ),
    ),
}


class FinancialService:
    def __init__(
        self,
        security_service: SecurityService,
        financial_provider: FinancialReportProviderProtocol,
    ):
        self._security_service = security_service
        self._financial_provider = financial_provider

    async def get_financial_data(
        self,
        company: str,
        metrics: list[FinancialMetric],
        *,
        year: int | None = None,
        quarter: int | None = None,
    ) -> CompanyFinancialData:
        if not metrics:
            raise ValueError("At least one financial metric is required")

        if quarter is not None and year is None:
            raise ValueError("A year is required when quarter is specified")

        if quarter is not None and quarter not in {1, 2, 3, 4}:
            raise ValueError("Quarter must be one of 1, 2, 3, 4")

        security = await self._security_service.resolve(company)

        unique_metrics = list(dict.fromkeys(metrics))
        statement_types = list(
            dict.fromkeys(
                METRIC_DEFINITIONS[metric].statement_type for metric in unique_metrics
            )
        )

        statements = await asyncio.gather(
            *[
                self._financial_provider.get_statement(
                    security,
                    statement_type,
                )
                for statement_type in statement_types
            ]
        )
        statement_by_type = {
            statement.statement_type: statement for statement in statements
        }

        values: list[FinancialMetricValue] = []

        for metric in unique_metrics:
            definition = METRIC_DEFINITIONS[metric]
            statement = statement_by_type[definition.statement_type]
            period = _select_period(
                statement,
                year=year,
                quarter=quarter,
            )
            source_field, value = _read_metric(
                period,
                definition,
            )
            display_value, display_unit = _format_value(
                value,
                definition.unit,
            )

            values.append(
                FinancialMetricValue(
                    metric=metric,
                    label=definition.label,
                    statement_type=definition.statement_type,
                    report_date=period.report_date,
                    value=value,
                    unit=definition.unit,
                    display_value=display_value,
                    display_unit=display_unit,
                    source_field=source_field,
                    publish_date=period.publish_date,
                    currency=period.currency,
                    audit_status=period.audit_status,
                    report_type=period.report_type,
                )
            )

        return CompanyFinancialData(
            security=security,
            values=values,
        )

    async def get_financial_series(
        self,
        company: str,
        metric: FinancialMetric,
        *,
        years: int = 5,
        end_year: int | None = None,
    ) -> FinancialMetricSeries:
        if years < 1:
            raise ValueError("Series years must be greater than zero")

        security = await self._security_service.resolve(company)
        definition = METRIC_DEFINITIONS[metric]
        statement = await self._financial_provider.get_statement(
            security,
            definition.statement_type,
        )

        annual_periods = sorted(
            (
                period
                for period in statement.periods
                if (
                    period.report_date.month,
                    period.report_date.day,
                )
                == (12, 31)
                and (end_year is None or period.report_date.year <= end_year)
            ),
            key=lambda period: period.report_date,
        )

        if not annual_periods:
            raise ValueError(
                "No annual financial reports are available for "
                f"{security.code} {security.name}"
            )

        if end_year is not None and annual_periods[-1].report_date.year != end_year:
            available = [period.report_date.year for period in annual_periods[-8:]]
            raise ValueError(
                f"Annual financial data is unavailable for {end_year}; "
                f"available recent years={available}"
            )

        selected_periods = annual_periods[-years:]
        points: list[FinancialSeriesPoint] = []

        for period in selected_periods:
            source_field, value = _read_metric(
                period,
                definition,
            )
            display_value, display_unit = _format_value(
                value,
                definition.unit,
            )

            points.append(
                FinancialSeriesPoint(
                    report_date=period.report_date,
                    value=value,
                    unit=definition.unit,
                    display_value=display_value,
                    display_unit=display_unit,
                    source_field=source_field,
                    publish_date=period.publish_date,
                    currency=period.currency,
                    audit_status=period.audit_status,
                    report_type=period.report_type,
                )
            )

        return FinancialMetricSeries(
            security=security,
            metric=metric,
            label=definition.label,
            statement_type=definition.statement_type,
            requested_years=years,
            end_year=selected_periods[-1].report_date.year,
            points=points,
        )


def _select_period(
    statement: FinancialStatement,
    *,
    year: int | None,
    quarter: int | None,
) -> FinancialStatementPeriod:
    if year is None:
        return max(
            statement.periods,
            key=lambda period: period.report_date,
        )

    month_day = {
        None: (12, 31),
        1: (3, 31),
        2: (6, 30),
        3: (9, 30),
        4: (12, 31),
    }[quarter]

    for period in statement.periods:
        if (
            period.report_date.year == year
            and (
                period.report_date.month,
                period.report_date.day,
            )
            == month_day
        ):
            return period

    period_label = (
        f"{year} annual report"
        if quarter is None or quarter == 4
        else f"{year} Q{quarter} report"
    )
    available = [period.report_date.isoformat() for period in statement.periods[:8]]

    raise ValueError(
        f"Financial data is unavailable for {period_label}; "
        f"available recent periods={available}"
    )


def _read_metric(
    period: FinancialStatementPeriod,
    definition: MetricDefinition,
) -> tuple[str | None, Decimal | None]:
    first_present_field: str | None = None

    for source_field in definition.source_fields:
        if source_field not in period.items:
            continue

        if first_present_field is None:
            first_present_field = source_field

        value = period.items[source_field]

        if value is not None:
            return source_field, value

    return first_present_field, None


def _format_value(
    value: Decimal | None,
    unit: str,
) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, None

    if unit == "CNY/share":
        return (
            value.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
            "元/股",
        )

    if unit != "CNY":
        return value, unit

    absolute_value = abs(value)

    if absolute_value >= Decimal("100000000"):
        return (
            (value / Decimal("100000000")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
            "亿元",
        )

    if absolute_value >= Decimal("10000"):
        return (
            (value / Decimal("10000")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
            "万元",
        )

    return (
        value.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        ),
        "元",
    )
