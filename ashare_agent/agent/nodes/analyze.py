from ..state import AgentState
from ..models import (
    EvidenceAssessment,
)

from ._utils import dumps


class AnalyzeNode:
    def __init__(
        self,
        model,
    ):
        self._model = model.with_structured_output(EvidenceAssessment)

    async def __call__(
        self,
        state: AgentState,
    ) -> dict:

        task = state["task"]

        results = state.get(
            "tool_results",
            [],
        )

        prompt = f"""
你是中国A股分析 Agent 的证据分析模块。

你的任务不是回答用户，而是判断目前获得的数据是否足够。

Task:

{dumps(task)}

工具结果：

{dumps(results)}

请判断：

1. sufficient:
   当前证据已经足够回答用户问题。

2. insufficient:
   当前证据还不够，但继续查询其他数据可能解决。

3. abnormal:
   当前结果存在明显异常、冲突、连续失败等问题。

同时判断本轮是否取得了实际进展 progress_made。

如果 insufficient，请在 missing 中说明还缺什么。

注意：

不要因为数据暂时不足就随便判断 abnormal。
必须核对工具结果中的公司、报告期和指标是否与用户问题明确要求的一致；
不相关的最新数据不能替代用户指定年份或季度的数据。
对于近N年问题，必须核对年度数值数量、截止年份和分析类型；
增长率和趋势必须来自工具的确定性计算结果，不能自行补算。
用户明确要求图表时，必须确认工具结果包含至少一个可用图片 artifact；
只有文字数据而没有 artifact 时证据仍然不足。
"""

        assessment = await self._model.ainvoke(prompt)

        old_no_progress = state.get(
            "no_progress_steps",
            0,
        )

        if assessment.progress_made:
            no_progress_steps = 0
        else:
            no_progress_steps = old_no_progress + 1

        return {
            "assessment": assessment,
            "no_progress_steps": (no_progress_steps),
        }
