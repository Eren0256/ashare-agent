from ..state import AgentState
from ..models import TaskDomain

from ._utils import (
    dumps,
    message_to_text,
)


class AnswerNode:
    def __init__(
        self,
        model,
    ):
        self._model = model

    async def __call__(
        self,
        state: AgentState,
    ) -> dict:

        task = state.get("task")

        if task is not None and task.domain == TaskDomain.OUT_OF_SCOPE:
            return {"final_answer": ("这个问题不属于A股分析范围。")}

        prompt = f"""
你是中国A股分析助手。

请根据当前状态回答用户的问题。

用户问题：

{state["question"]}

Task:

{dumps(task)}

Decision:

{dumps(state.get("decision"))}

工具结果：

{dumps(state.get("tool_results", []))}

Evidence Assessment:

{dumps(state.get("assessment"))}

Reflection:

{dumps(state.get("reflection"))}

要求：

1. 直接回答用户问题。
2. 不要描述 Agent 内部执行流程。
3. 有可靠工具数据时，以工具数据为准。
4. 数据不足时明确说明不足，不要编造事实。
5. 不要暴露无意义的内部工具名称。
6. 回答尽量简洁。
7. 回答财务数据时说明报告期和单位；数值较大时可以换算为亿或万，
   但必须保持数值准确。
8. 利润表和现金流量表的季度数据通常为年初至报告期末累计值，
   不要将其描述为单季度数据。
9. 工具结果没有覆盖用户指定报告期时，只能说明当前证据不足，
   不要据此断言对应财报尚未披露。
10. 财务序列结果提供 display_value、display_unit、同比和 CAGR 时，
    直接使用这些字段，不要自行重新换算或重新计算。
11. 趋势描述必须有年度序列和增长率支持；存在 warnings 时明确说明。
12. 用户要求绘图且工具生成了 artifacts 时，简洁说明图表已经生成；
    不要在正文输出文件路径、Markdown 图片语法或自行构造图片链接，
    图片会通过 AgentResponse.artifacts 单独返回。
13. 不要把数值变化臆测成价格竞争、成本压力等原因；只有工具提供了
    相关证据时才能解释原因。
"""

        response = await self._model.ainvoke(prompt)

        return {"final_answer": (message_to_text(response))}
