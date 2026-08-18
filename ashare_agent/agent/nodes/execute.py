import asyncio

from pydantic import BaseModel

from ..state import AgentState

from ashare_agent.tools.models import (
    ToolCall,
    ToolResult,
)
from ashare_agent.domain import ChartArtifact


class ExecuteToolNode:
    def __init__(
        self,
        tool_registry,
    ):
        self._tool_registry = tool_registry

    async def __call__(
        self,
        state: AgentState,
    ) -> dict:

        calls = state.get(
            "pending_tool_calls",
            [],
        )

        if not calls:
            return {}

        results = await asyncio.gather(*[self._execute(call) for call in calls])

        old_results = state.get(
            "tool_results",
            [],
        )

        history = state.get(
            "tool_call_history",
            [],
        )

        old_artifacts = state.get(
            "artifacts",
            [],
        )
        new_artifacts = _collect_artifacts(results)

        return {
            "tool_results": (old_results + results),
            "tool_call_history": (history + [calls]),
            "pending_tool_calls": [],
            "artifacts": _merge_artifacts(
                old_artifacts,
                new_artifacts,
            ),
        }

    async def _execute(
        self,
        call: ToolCall,
    ) -> ToolResult:

        try:
            return await self._tool_registry.execute(call)

        except Exception as exc:
            return ToolResult(
                tool_name=call.tool_name,
                success=False,
                data=None,
                error=str(exc),
            )


def _collect_artifacts(
    value,
) -> list[ChartArtifact]:
    artifacts: list[ChartArtifact] = []

    def visit(item) -> None:
        if isinstance(item, ChartArtifact):
            artifacts.append(item)
            return

        if isinstance(item, BaseModel):
            for field_name in type(item).model_fields:
                visit(getattr(item, field_name))
            return

        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
            return

        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return artifacts


def _merge_artifacts(
    old_artifacts: list[ChartArtifact],
    new_artifacts: list[ChartArtifact],
) -> list[ChartArtifact]:
    by_id = {artifact.artifact_id: artifact for artifact in old_artifacts}

    for artifact in new_artifacts:
        by_id[artifact.artifact_id] = artifact

    return list(by_id.values())
