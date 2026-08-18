from typing import Protocol

from ashare_agent.agent import (
    AShareAnalysisAgent,
    AgentResponse,
    ConversationMessage,
)


class AgentRuntimeProtocol(Protocol):
    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse: ...


class AShareAgentRuntime:
    def __init__(
        self,
        agent: AShareAnalysisAgent | None = None,
    ):
        self._agent = agent or AShareAnalysisAgent()

    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse:
        messages = [
            ConversationMessage.model_validate(item)
            for item in context
        ]
        return await self._agent.run_with_artifacts(
            question,
            context=messages,
        )
