from typing import Any, Protocol

from pydantic import (
    BaseModel,
    Field,
)

from ..base import BaseTool


class CompanyServiceProtocol(Protocol):
    async def get_business(
        self,
        company: str,
    ) -> Any: ...


class GetCompanyBusinessArgs(BaseModel):
    company: str = Field(
        description=("公司名称、股票简称或者股票代码。例如：茅台、贵州茅台、600519")
    )


class GetCompanyBusinessTool(BaseTool):
    name = "get_company_business"

    description = "查询中国A股上市公司的主营业务、主要产品等公司业务信息。"

    intents = ("company_business",)

    keywords = (
        "主营业务",
        "主要业务",
        "主营",
        "业务范围",
        "做什么",
        "产品",
    )

    args_model = GetCompanyBusinessArgs

    def __init__(
        self,
        company_service: CompanyServiceProtocol,
    ):
        self._company_service = company_service

    async def run(
        self,
        args: GetCompanyBusinessArgs,
    ) -> Any:

        return await self._company_service.get_business(company=args.company)
