from .understand import UnderstandNode
from .plan import PlanNode
from .execute import ExecuteToolNode
from .analyze import AnalyzeNode
from .reflect import ReflectNode
from .answer import AnswerNode


def create_default_nodes():
    # 延迟 import，避免模块初始化阶段出现
    # 不必要的依赖加载和循环依赖

    from ashare_agent.llm import (
        create_default_model,
    )

    from ashare_agent.tools import (
        create_default_tool_registry,
        create_default_tool_selector,
    )

    model = create_default_model()

    tool_registry = create_default_tool_registry()

    tool_selector = create_default_tool_selector(tool_registry)

    return {
        "understand": UnderstandNode(model),
        "plan": PlanNode(
            model,
            tool_selector,
        ),
        "execute": ExecuteToolNode(tool_registry),
        "analyze": AnalyzeNode(model),
        "reflect": ReflectNode(model),
        "answer": AnswerNode(model),
    }


__all__ = [
    "UnderstandNode",
    "PlanNode",
    "ExecuteToolNode",
    "AnalyzeNode",
    "ReflectNode",
    "AnswerNode",
    "create_default_nodes",
]
