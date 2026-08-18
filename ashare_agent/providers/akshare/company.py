import asyncio
import akshare as ak

from ashare_agent.domain import Security, CompanyBusiness


class AkshareCompanyProvider:
    async def get_business(self, security: Security) -> CompanyBusiness:
        df = await asyncio.to_thread(ak.stock_zyjs_ths, symbol=security.code)
        if df is None or df.empty:
            raise RuntimeError(
                f"No company business data:" f"{security.code} {security.name}"
            )

        required_columns = {
            "主营业务",
            "产品类型",
            "产品名称",
            "经营范围",
        }
        missing = required_columns - set(df.columns)
        if missing:
            raise RuntimeError(
                f"AKShare company business columns changed: "
                f"missing={sorted(missing)}"
            )

        row = df.iloc[0]
        return CompanyBusiness(
            security=security,
            main_business=row["主营业务"],
            product_types=row["产品类型"],
            products=row["产品名称"],
            business_scope=row["经营范围"],
        )
