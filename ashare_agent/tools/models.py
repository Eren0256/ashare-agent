from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """
    Planner 生成的工具调用请求。
    """

    tool_name: str

    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """
    工具执行后的统一返回格式。
    """

    tool_name: str

    success: bool

    data: Any = None

    error: str | None = None


class ToolSpec(BaseModel):
    """
    给 ToolSelector / Planner 看的工具说明。
    """

    name: str

    description: str

    # 这个工具适合处理哪些 intent
    intents: list[str] = Field(default_factory=list)

    # 用于简单检索
    keywords: list[str] = Field(default_factory=list)

    # Planner 需要知道工具参数怎么传
    input_schema: dict[str, Any] = Field(default_factory=dict)
