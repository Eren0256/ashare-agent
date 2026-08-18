import asyncio

import akshare as ak

from ashare_agent.domain import Security


class AkshareSecurityProvider:
    async def list_securities(self) -> list[Security]:
        df = await asyncio.to_thread(ak.stock_info_a_code_name)

        if df is None or df.empty:
            raise RuntimeError("AKShare returned empty security list")

        required_columns = {"code", "name"}

        missing = required_columns - set(df.columns)

        if missing:
            raise RuntimeError(
                f"AKShare security columns changed:" f"missing={sorted(missing)}"
            )

        securities: list[Security] = []
        for _, row in df.iterrows():
            code = str(row["code"]).strip()
            name = str(row["name"]).strip()
            if not code or not name:
                continue
            securities.append(Security(code=code.zfill(6), name=name))

        return securities
