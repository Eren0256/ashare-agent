from .graph import (
    create_default_graph,
)

from .state import AgentState
from .models import AgentResponse, ConversationMessage


class AShareAnalysisAgent:
    def __init__(
        self,
        graph=None,
    ):
        self._graph = graph if graph is not None else create_default_graph()

    async def run(
        self,
        question: str,
        context: list[ConversationMessage] | None = None,
    ) -> str:

        response = await self.run_with_artifacts(
            question,
            context=context,
        )

        return response.text

    async def run_with_artifacts(
        self,
        question: str,
        context: list[ConversationMessage] | None = None,
    ) -> AgentResponse:

        question = question.strip()

        if not question:
            raise ValueError("question cannot be empty")

        initial_state: AgentState = {
            "question": question,
            "conversation_context": list(context or []),
        }

        result = await self._graph.ainvoke(initial_state)

        final_answer = result.get("final_answer")

        if not final_answer:
            raise RuntimeError("Agent finished without " "producing final_answer")

        return AgentResponse(
            text=final_answer,
            artifacts=result.get("artifacts", []),
        )
