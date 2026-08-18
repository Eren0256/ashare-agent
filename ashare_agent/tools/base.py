from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .models import ToolSpec


class BaseTool(ABC):
    """
    所有 Agent Tool 的统一基类。
    """

    name: str

    description: str

    intents: tuple[str, ...] = ()

    keywords: tuple[str, ...] = ()

    args_model: type[BaseModel]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            intents=list(self.intents),
            keywords=list(self.keywords),
            input_schema=(self.args_model.model_json_schema()),
        )

    async def execute(
        self,
        arguments: dict[str, Any],
    ) -> Any:
        """
        统一做参数校验，然后调用具体工具。
        """

        args = self.args_model.model_validate(arguments)

        return await self.run(args)

    @abstractmethod
    async def run(
        self,
        args: BaseModel,
    ) -> Any:
        pass
