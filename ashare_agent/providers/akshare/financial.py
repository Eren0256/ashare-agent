import asyncio
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from typing import Any

import akshare as ak
import pandas as pd

from ashare_agent.domain import (
    FinancialStatement,
    FinancialStatementPeriod,
    FinancialStatementType,
    Security,
)

_STATEMENT_SYMBOLS = {
    FinancialStatementType.BALANCE_SHEET: "资产负债表",
    FinancialStatementType.INCOME_STATEMENT: "利润表",
    FinancialStatementType.CASH_FLOW_STATEMENT: "现金流量表",
}

_METADATA_COLUMNS = {
    "报告日",
    "数据源",
    "是否审计",
    "公告日期",
    "币种",
    "类型",
    "更新日期",
}


class AkshareFinancialReportProvider:
    async def get_statement(
        self,
        security: Security,
        statement_type: FinancialStatementType,
    ) -> FinancialStatement:
        stock = _to_sina_stock_code(security.code)
        symbol = _STATEMENT_SYMBOLS[statement_type]

        df = await asyncio.to_thread(
            ak.stock_financial_report_sina,
            stock=stock,
            symbol=symbol,
        )

        if df is None or df.empty:
            raise RuntimeError(
                "AKShare returned an empty financial statement: "
                f"{security.code} {security.name}; statement={symbol}"
            )

        if "报告日" not in df.columns:
            raise RuntimeError(
                "AKShare financial statement columns changed: " "missing=['报告日']"
            )

        item_columns = [
            str(column) for column in df.columns if str(column) not in _METADATA_COLUMNS
        ]

        periods: list[FinancialStatementPeriod] = []

        for _, row in df.iterrows():
            report_date = _parse_date(row.get("报告日"))

            if report_date is None:
                continue

            items = {column: _to_decimal(row.get(column)) for column in item_columns}

            periods.append(
                FinancialStatementPeriod(
                    report_date=report_date,
                    publish_date=_parse_date(row.get("公告日期")),
                    currency=_clean_text(row.get("币种")),
                    audit_status=_clean_text(row.get("是否审计")),
                    report_type=_clean_text(row.get("类型")),
                    items=items,
                )
            )

        if not periods:
            raise RuntimeError(
                "AKShare financial statement has no valid report periods: "
                f"{security.code} {security.name}; statement={symbol}"
            )

        periods.sort(
            key=lambda period: period.report_date,
            reverse=True,
        )

        return FinancialStatement(
            security=security,
            statement_type=statement_type,
            periods=periods,
        )


def _to_sina_stock_code(
    code: str,
) -> str:
    if code.startswith("6"):
        return f"sh{code}"

    if code.startswith(("0", "3")):
        return f"sz{code}"

    raise ValueError(
        "Sina financial reports currently only support Shanghai and "
        f"Shenzhen A-share codes: {code}"
    )


def _to_decimal(
    value: Any,
) -> Decimal | None:
    if _is_missing(value):
        return None

    try:
        if isinstance(value, Integral):
            return Decimal(int(value))

        if isinstance(value, Real):
            # AKShare converts report values to floating-point numbers.
            # Formatting to 15 significant digits removes binary artifacts
            # such as 150560330316.44998 for an original .45 value.
            return Decimal(format(value, ".15g"))

        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_date(
    value: Any,
) -> date | None:
    text = _clean_text(value)

    if text is None:
        return None

    normalized = text.replace("/", "-")

    for format_string in (
        "%Y%m%d",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(
                normalized,
                format_string,
            ).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _clean_text(
    value: Any,
) -> str | None:
    if _is_missing(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    return text


def _is_missing(
    value: Any,
) -> bool:
    if value is None:
        return True

    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False

    try:
        return bool(missing)
    except (TypeError, ValueError):
        return False
