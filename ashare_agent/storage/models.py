from enum import Enum
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class UserRecord(BaseModel):
    id: str
    username: str
    display_name: str
    password_hash: str
    is_active: bool = True


class SessionRecord(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageRecord(BaseModel):
    id: str
    session_id: str
    user_id: str
    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ArtifactRecord(BaseModel):
    id: str
    source_artifact_id: str
    job_id: str
    message_id: str
    session_id: str
    user_id: str
    title: str
    mime_type: str
    storage_key: str
    width: int
    height: int
    chart_type: str
    created_at: datetime

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.id,
            "type": "image",
            "title": self.title,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "chart_type": self.chart_type,
            "url": f"/artifacts/{self.id}",
        }


class JobRecord(BaseModel):
    id: str
    session_id: str
    user_id: str
    user_message_id: str
    status: JobStatus
    question: str
    result_text: str | None = None
    assistant_message_id: str | None = None
    error: str | None = None
    error_type: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    artifacts: list[ArtifactRecord] = Field(default_factory=list)


class SubmittedTurn(BaseModel):
    job: JobRecord
    user_message: MessageRecord
    context: list[dict[str, str]] = Field(default_factory=list)
