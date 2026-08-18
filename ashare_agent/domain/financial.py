from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from .security import Security


class FinancialStatementType(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW_STATEMENT = "cash_flow_statement"


class FinancialMetric(str, Enum):
    # 资产负债表
    CASH = "cash"  # 货币资金
    ACCOUNTS_RECEIVABLE = "accounts_receivable"  # 应收账款
    INVENTORY = "inventory"  # 存货
    CURRENT_ASSETS = "current_assets"  # 流动资产合计
    TOTAL_ASSETS = "total_assets"  # 资产总计
    CURRENT_LIABILITIES = "current_liabilities"  # 流动负债合计
    TOTAL_LIABILITIES = "total_liabilities"  # 负债合计
    PARENT_EQUITY = "parent_equity"  # 归母股东权益合计
    TOTAL_EQUITY = "total_equity"  # 所有者权益合计

    # 利润表
    REVENUE = "revenue"  # 营业收入
    TOTAL_REVENUE = "total_revenue"  # 营业总收入
    OPERATING_COST = "operating_cost"  # 营业成本
    OPERATING_PROFIT = "operating_profit"  # 营业利润
    TOTAL_PROFIT = "total_profit"  # 利润总额
    NET_PROFIT = "net_profit"  # 净利润
    PARENT_NET_PROFIT = "parent_net_profit"  # 归母净利润
    BASIC_EPS = "basic_eps"  # 基本每股收益

    # 现金流量表
    OPERATING_CASH_FLOW = "operating_cash_flow"  # 经营活动现金流净额
    INVESTING_CASH_FLOW = "investing_cash_flow"  # 投资活动现金流净额
    FINANCING_CASH_FLOW = "financing_cash_flow"  # 筹资活动现金流净额
    NET_CASH_INCREASE = "net_cash_increase"  # 现金净增加额
    ENDING_CASH_EQUIVALENTS = "ending_cash_equivalents"  # 期末现金余额


class FinancialAnalysisType(str, Enum):
    VALUES = "values"  # 查询多个年度的原始数值
    YOY = "yoy"  # 计算逐年同比增长率
    CAGR = "cagr"  # 计算区间复合年增长率
    TREND = "trend"  # 判断整体增长或下降趋势


class FinancialGrowthStatus(str, Enum):
    BASELINE = "baseline"  # 序列首期，没有上期数据可比较
    AVAILABLE = "available"  # 数据正常，可以计算增长率
    MISSING_VALUE = "missing_value"  # 本期或上期数值缺失
    PERIOD_GAP = "period_gap"  # 报告期不连续，不能计算同比
    ZERO_BASE = "zero_base"  # 上期数值为零，不能计算增长率
    NEGATIVE_BASE = "negative_base"  # 上期为负数，普通增速无意义
    TURNAROUND = "turnaround"  # 从亏损转为盈利
    TURNED_TO_LOSS = "turned_to_loss"  # 从盈利转为亏损


class FinancialTrendDirection(str, Enum):
    CONTINUOUS_GROWTH = "continuous_growth"  # 每个有效年度都增长
    CONTINUOUS_DECLINE = "continuous_decline"  # 每个有效年度都下降
    VOLATILE_GROWTH = "volatile_growth"  # 有涨有跌但整体增长
    VOLATILE_DECLINE = "volatile_decline"  # 有涨有跌但整体下降
    STABLE = "stable"  # 各期数值基本不变
    MIXED = "mixed"  # 涨跌交替且整体方向不明确
    INSUFFICIENT_DATA = "insufficient_data"  # 有效数据不足


class FinancialStatementPeriod(BaseModel):
    report_date: date
    publish_date: date | None = None
    currency: str | None = None
    audit_status: str | None = None
    report_type: str | None = None
    items: dict[str, Decimal | None] = Field(default_factory=dict)


class FinancialStatement(BaseModel):
    security: Security
    statement_type: FinancialStatementType
    periods: list[FinancialStatementPeriod] = Field(default_factory=list)


class FinancialMetricValue(BaseModel):
    metric: FinancialMetric
    label: str
    statement_type: FinancialStatementType
    report_date: date
    value: Decimal | None
    unit: str
    display_value: Decimal | None = None
    display_unit: str | None = None
    source_field: str | None = None
    publish_date: date | None = None
    currency: str | None = None
    audit_status: str | None = None
    report_type: str | None = None


class CompanyFinancialData(BaseModel):
    security: Security
    values: list[FinancialMetricValue] = Field(default_factory=list)


class FinancialSeriesPoint(BaseModel):
    report_date: date
    value: Decimal | None
    unit: str
    display_value: Decimal | None = None
    display_unit: str | None = None
    source_field: str | None = None
    publish_date: date | None = None
    currency: str | None = None
    audit_status: str | None = None
    report_type: str | None = None


class FinancialMetricSeries(BaseModel):
    security: Security
    metric: FinancialMetric
    label: str
    statement_type: FinancialStatementType
    requested_years: int
    end_year: int
    points: list[FinancialSeriesPoint] = Field(default_factory=list)


class FinancialGrowthPoint(BaseModel):
    report_date: date
    value: Decimal | None
    previous_report_date: date | None = None
    previous_value: Decimal | None = None
    yoy_rate_percent: Decimal | None = None
    status: FinancialGrowthStatus


class FinancialMetricAnalysis(BaseModel):
    series: FinancialMetricSeries
    growth_points: list[FinancialGrowthPoint] = Field(default_factory=list)
    overall_growth_rate_percent: Decimal | None = None
    cagr_percent: Decimal | None = None
    positive_years: int = 0
    negative_years: int = 0
    unchanged_years: int = 0
    trend_direction: FinancialTrendDirection | None = None
    warnings: list[str] = Field(default_factory=list)


class CompanyFinancialAnalysis(BaseModel):
    security: Security
    analysis_types: list[FinancialAnalysisType]
    metrics: list[FinancialMetricAnalysis] = Field(default_factory=list)
