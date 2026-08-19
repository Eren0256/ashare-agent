from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class QueuedJob:
    message_id: str
    job_id: str
    reclaimed: bool = False


class JobQueueProtocol(Protocol):
    async def start(self) -> None: ...

    async def publish(self, job_id: str) -> str: ...

    async def receive(
        self,
        consumer_name: str,
        *,
        block_ms: int,
    ) -> QueuedJob | None: ...

    async def acknowledge(self, message_id: str) -> None: ...

    async def close(self) -> None: ...
