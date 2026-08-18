from pydantic import BaseModel, Field

from ..state import AgentState

from ..models import (
    ActionType,
    Decision,
)

from ashare_agent.tools.models import (
    ToolCall,
)

from ._utils import dumps


class PlanOutput(BaseModel):
    action: ActionType

    reason: str | None = None

    tool_calls: list[ToolCall] = Field(default_factory=list)


class PlanNode:
    def __init__(
        self,
        model,
        tool_selector,
        *,
        top_k: int = 8,
        max_iterations: int = 8,
    ):
        self._model = model.with_structured_output(PlanOutput)

        self._tool_selector = tool_selector

        self._top_k = top_k

        self._max_iterations = max_iterations

    async def __call__(
        self,
        state: AgentState,
    ) -> dict:

        current_iteration = state.get(
            "iteration",
            0,
        )

        if current_iteration >= self._max_iterations:
            return {
                "iteration": current_iteration,
                "decision": Decision(
                    action=ActionType.FAIL,
                    reason="已达到最大规划次数",
                ),
                "pending_tool_calls": [],
            }

        iteration = current_iteration + 1

        task = state["task"]

        candidates = await self._tool_selector.aselect(
            query=state["question"],
            task=task,
            top_k=self._top_k,
        )

        recent_results = state.get(
            "tool_results",
            [],
        )[-8:]

        assessment = state.get("assessment")

        reflection = state.get("reflection")

        prompt = f"""
你是中国A股分析 Agent 的 Planner。

你的任务是决定下一步应该做什么。

可以选择：

call_tool
answer
unsupported
fail

Task:

{dumps(task)}

当前候选工具：

{dumps(candidates)}

已有工具结果：

{dumps(recent_results)}

上一轮证据分析：

{dumps(assessment)}

Reflection:

{dumps(reflection)}

规则：

1. 如果还需要外部数据，选择 call_tool。
2. call_tool 只能选择候选工具中存在的工具。
3. 不要重复已经证明无效的工具策略。
4. 如果现有信息已经足够回答，选择 answer。
5. 如果需求属于A股领域但当前系统能力确实无法完成，
   选择 unsupported。
6. 如果系统处于无法恢复的错误状态，选择 fail。
7. 工具参数必须保留用户明确给出的公司、年份、季度和指标等约束，
   不得把指定年份替换成最新一期。
8. 只查询回答问题所必需的数据，不要擅自添加用户没有询问的指标。
"""

        plan = await self._model.ainvoke(prompt)

        if plan.action == ActionType.CALL_TOOL:
            valid_names = {_tool_name(tool) for tool in candidates if _tool_name(tool)}

            valid_calls = [
                call for call in plan.tool_calls if call.tool_name in valid_names
            ]

            if not valid_calls:
                return {
                    "iteration": iteration,
                    "decision": Decision(
                        action=ActionType.FAIL,
                        reason=("Planner 未生成有效的工具调用"),
                    ),
                    "pending_tool_calls": [],
                }

            return {
                "iteration": iteration,
                "decision": Decision(
                    action=ActionType.CALL_TOOL,
                    reason=plan.reason,
                ),
                "pending_tool_calls": (valid_calls),
            }

        return {
            "iteration": iteration,
            "decision": Decision(
                action=plan.action,
                reason=plan.reason,
            ),
            "pending_tool_calls": [],
        }


def _tool_name(tool):
    if isinstance(tool, dict):
        return tool.get("name")

    return getattr(
        tool,
        "name",
        None,
    )
