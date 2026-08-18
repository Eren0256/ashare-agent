from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from ashare_agent.domain import FinancialMetric

from ..base import BaseTool


class FinancialServiceProtocol(Protocol):
    async def get_financial_data(
        self,
        company: str,
        metrics: list[FinancialMetric],
        *,
        year: int | None = None,
        quarter: int | None = None,
    ) -> Any: ...


class FinancialPeriodMode(str, Enum):
    LATEST = "latest"
    ANNUAL = "annual"
    QUARTER = "quarter"


class GetCompanyFinancialDataArgs(BaseModel):
    company: str = Field(
        description=("公司名称、股票简称或者股票代码，例如贵州茅台、600519")
    )

    metrics: list[FinancialMetric] = Field(
        min_length=1,
        max_length=6,
        description=(
            "只选择用户明确询问的基础财务指标，不要添加用户没有询问的指标。"
            "资产负债表：cash=货币资金，accounts_receivable=应收账款，"
            "inventory=存货，current_assets=流动资产合计，"
            "total_assets=资产总计，current_liabilities=流动负债合计，"
            "total_liabilities=负债合计，parent_equity=归母股东权益，"
            "total_equity=所有者权益合计；"
            "利润表：revenue=营业收入，total_revenue=营业总收入，"
            "operating_cost=营业成本，operating_profit=营业利润，"
            "total_profit=利润总额，net_profit=净利润，"
            "parent_net_profit=归母净利润，basic_eps=基本每股收益；"
            "现金流量表：operating_cash_flow=经营活动现金流量净额，"
            "investing_cash_flow=投资活动现金流量净额，"
            "financing_cash_flow=筹资活动现金流量净额，"
            "net_cash_increase=现金及现金等价物净增加额，"
            "ending_cash_equivalents=期末现金及现金等价物余额。"
        ),
    )

    period_mode: FinancialPeriodMode = Field(
        description=(
            "必须按用户问题选择报告期模式：latest=用户询问最新一期；"
            "annual=用户指定某一年度或年报；quarter=用户指定某年某季度。"
            "用户明确写出年份时禁止选择 latest。"
        )
    )

    year: int | None = Field(
        default=None,
        ge=1990,
        le=2100,
        description=("用户明确写出的报告年度。period_mode=annual 或 quarter 时必填。"),
    )

    quarter: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description=(
            "季度，可选 1、2、3、4；必须同时指定 year。"
            "利润表和现金流量表的季度数据通常是年初至报告期末累计值。"
        ),
    )

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_mode == FinancialPeriodMode.LATEST:
            if self.year is not None or self.quarter is not None:
                raise ValueError("latest period must not specify year or quarter")

        elif self.period_mode == FinancialPeriodMode.ANNUAL:
            if self.year is None:
                raise ValueError("annual period requires year")

            if self.quarter is not None:
                raise ValueError("annual period must not specify quarter")

        elif self.period_mode == FinancialPeriodMode.QUARTER:
            if self.year is None or self.quarter is None:
                raise ValueError("quarter period requires year and quarter")

        return self


class GetCompanyFinancialDataTool(BaseTool):
    name = "get_company_financial_data"

    description = (
        "查询一家中国A股上市公司在指定年报、季度报告或最新报告期中的"
        "资产负债表、利润表和现金流量表基础数据。"
        "必须准确传递用户明确给出的年份和季度，并且只查询用户要求的指标。"
        "支持一次查询多个基础指标，但不计算增长率、财务比率或预测值。"
    )

    intents = ("financial_statement",)

    keywords = (
        "财务",
        "财报",
        "资产负债表",
        "利润表",
        "现金流量表",
        "营收",
        "收入",
        "利润",
        "资产",
        "负债",
        "股东权益",
        "现金流",
        "每股收益",
        "应收账款",
        "存货",
    )

    args_model = GetCompanyFinancialDataArgs

    def __init__(
        self,
        financial_service: FinancialServiceProtocol,
    ):
        self._financial_service = financial_service

    async def run(
        self,
        args: GetCompanyFinancialDataArgs,
    ) -> Any:
        return await self._financial_service.get_financial_data(
            company=args.company,
            metrics=args.metrics,
            year=(
                None if args.period_mode == FinancialPeriodMode.LATEST else args.year
            ),
            quarter=(
                args.quarter
                if args.period_mode == FinancialPeriodMode.QUARTER
                else None
            ),
        )
