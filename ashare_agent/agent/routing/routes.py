import json

from ..state import AgentState
from ..models import TaskDomain, ActionType, AnalysisStatus


def route_after_understand(state: AgentState) -> str:
    task = state["task"]
    if task.domain == TaskDomain.OUT_OF_SCOPE:
        return "answer"
    return "plan"


def route_after_plan(state: AgentState) -> str:
    decision = state["decision"]
    if decision.action == ActionType.CALL_TOOL:
        return "execute"
    return "answer"


def route_after_analyze(state: AgentState) -> str:
    assessment = state["assessment"]
    if assessment.status == AnalysisStatus.SUFFICIENT:
        return "answer"
    if assessment.status == AnalysisStatus.ABNORMAL:
        return "reflect"
    if should_reflect(state):
        return "reflect"
    return "plan"


def route_after_reflect(state: AgentState) -> str:
    reflection = state["reflection"]
    if reflection.should_continue:
        return "plan"
    return "answer"


def should_reflect(
    state: AgentState,
) -> bool:

    # 连续没有取得进展
    if state.get("no_progress_steps", 0) >= 2:
        return True

    # 连续两轮执行完全相同的工具调用
    history = state.get(
        "tool_call_history",
        [],
    )

    if len(history) >= 2:
        previous = _tool_batch_signature(history[-2])

        current = _tool_batch_signature(history[-1])

        if previous == current:
            return True

    # 连续工具失败
    results = state.get(
        "tool_results",
        [],
    )

    if len(results) >= 2:
        if not results[-1].success and not results[-2].success:
            return True

    return False


def _tool_batch_signature(
    calls,
) -> str:

    data = []

    for call in calls:
        if hasattr(call, "model_dump"):
            item = call.model_dump(mode="json")
        else:
            item = str(call)

        data.append(item)

    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
