from ..state import AgentState
from ..models import Reflection

from ._utils import dumps


class ReflectNode:
    def __init__(
        self,
        model,
        *,
        max_reflections: int = 2,
    ):
        self._model = model.with_structured_output(Reflection)

        self._max_reflections = max_reflections

    async def __call__(
        self,
        state: AgentState,
    ) -> dict:

        current_count = state.get(
            "reflection_count",
            0,
        )

        if current_count >= self._max_reflections:
            return {
                "reflection_count": (current_count),
                "reflection": Reflection(
                    root_cause=("多次尝试仍未取得有效进展"),
                    should_continue=False,
                    stop_reason=("已达到最大反思次数"),
                ),
            }

        reflection_count = current_count + 1

        prompt = f"""
你是中国A股分析 Agent 的异常恢复模块。

正常的 Plan -> Execute -> Analyze 流程已经没有取得有效进展。

你的任务不是重新回答用户问题，而是分析：

1. 为什么之前的策略没有效果？
2. 哪些工具或策略应该避免？
3. 下一轮应该采用什么不同策略？
4. 是否还有继续尝试的价值？

Task:

{dumps(state.get("task"))}

Evidence Assessment:

{dumps(state.get("assessment"))}

Tool Call History:

{dumps(state.get("tool_call_history", []))}

Tool Results:

{dumps(state.get("tool_results", []))}
"""

        reflection = await self._model.ainvoke(prompt)

        return {
            "reflection": reflection,
            "reflection_count": (reflection_count),
        }
