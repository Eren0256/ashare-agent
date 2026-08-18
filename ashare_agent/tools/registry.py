from .base import BaseTool

from .models import (
    ToolCall,
    ToolResult,
    ToolSpec,
)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[
            str,
            BaseTool,
        ] = {}

    def register(
        self,
        tool: BaseTool,
    ) -> None:

        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: " f"{tool.name}")

        self._tools[tool.name] = tool

    def get(
        self,
        name: str,
    ) -> BaseTool | None:

        return self._tools.get(name)

    def specs(
        self,
    ) -> list[ToolSpec]:

        return [tool.spec for tool in self._tools.values()]

    def names(
        self,
    ) -> list[str]:

        return list(self._tools.keys())

    async def execute(
        self,
        call: ToolCall,
    ) -> ToolResult:

        tool = self.get(call.tool_name)

        if tool is None:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error=(f"Unknown tool: " f"{call.tool_name}"),
            )

        try:
            data = await tool.execute(call.arguments)

            return ToolResult(
                tool_name=call.tool_name,
                success=True,
                data=data,
            )

        except Exception as exc:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                error=str(exc),
            )
