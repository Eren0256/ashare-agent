from typing import TypedDict

from .models import (
    ConversationMessage,
    Decision,
    EvidenceAssessment,
    Reflection,
    TaskSpec,
)

from ashare_agent.tools.models import ToolCall, ToolResult
from ashare_agent.domain import ChartArtifact


class AgentState(TypedDict, total=False):

    # Input

    question: str
    conversation_context: list[ConversationMessage]

    # UnderstandNode

    task: TaskSpec

    # PlanNode

    decision: Decision
    pending_tool_calls: list[ToolCall]

    # ExecuteToolNode

    tool_results: list[ToolResult]
    tool_call_history: list[list[ToolCall]]

    # AnalyzeNode

    assessment: EvidenceAssessment
    no_progress_steps: int

    # ReflectNode

    reflection: Reflection
    reflection_count: int

    # Runtime
    iteration: int

    # Generated artifacts

    artifacts: list[ChartArtifact]

    # AnswerNode

    final_answer: str
