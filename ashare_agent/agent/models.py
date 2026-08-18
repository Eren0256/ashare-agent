from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from ashare_agent.domain import (
    ChartArtifact,
    FinancialAnalysisType,
    FinancialMetric,
    ResponseOutputMode,
)


class TaskDomain(str, Enum):
    A_SHARE = "a_share"
    OUT_OF_SCOPE = "out_of_scope"


class ActionType(str, Enum):
    CALL_TOOL = "call_tool"
    ANSWER = "answer"
    UNSUPPORTED = "unsupported"
    FAIL = "fail"


class AnalysisStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    ABNORMAL = "abnormal"


class TaskSpec(BaseModel):
    domain: TaskDomain
    intent: str | None = None
    entities: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1990, le=2100)
    quarter: int | None = Field(default=None, ge=1, le=4)
    financial_metrics: list[FinancialMetric] = Field(default_factory=list)
    lookback_years: int | None = Field(
        default=None,
        ge=2,
        le=10,
    )
    financial_analyses: list[FinancialAnalysisType] = Field(default_factory=list)
    output_modes: list[ResponseOutputMode] = Field(
        default_factory=lambda: [ResponseOutputMode.TEXT]
    )


class AgentResponse(BaseModel):
    text: str
    artifacts: list[ChartArtifact] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class Decision(BaseModel):
    action: ActionType
    reason: str | None = None


class EvidenceAssessment(BaseModel):
    status: AnalysisStatus
    reason: str | None = None
    missing: list[str] = Field(default_factory=list)
    progress_made: bool = True


class Reflection(BaseModel):
    root_cause: str
    suggested_strategy: str | None = None
    avoid_tools: list[str] = Field(default_factory=list)
    should_continue: bool = True
    stop_reason: str | None = None
