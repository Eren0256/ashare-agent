from collections import deque
from threading import Lock

from ashare_agent.queue import QueuedJob
from ashare_agent.storage import AppDatabase


def sqlite_test_database(path) -> AppDatabase:
    return AppDatabase(
        f"sqlite+aiosqlite:///{path}",
        create_schema=True,
    )


class MemoryJobQueue:
    def __init__(self) -> None:
        self._available: deque[QueuedJob] = deque()
        self._pending: dict[str, QueuedJob] = {}
        self._next_id = 1
        self._lock = Lock()
        self.acknowledged: list[str] = []

    async def start(self) -> None:
        return None

    async def publish(self, job_id: str) -> str:
        with self._lock:
            message_id = f"{self._next_id}-0"
            self._next_id += 1
            self._available.append(
                QueuedJob(message_id=message_id, job_id=job_id)
            )
            return message_id

    async def receive(
        self,
        consumer_name: str,
        *,
        block_ms: int,
    ) -> QueuedJob | None:
        del consumer_name, block_ms
        with self._lock:
            if not self._available:
                return None
            message = self._available.popleft()
            self._pending[message.message_id] = message
            return message

    async def acknowledge(self, message_id: str) -> None:
        with self._lock:
            self._pending.pop(message_id, None)
            self.acknowledged.append(message_id)

    async def close(self) -> None:
        return None

    def redeliver_pending(self) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
            for message in pending:
                self._available.append(
                    QueuedJob(
                        message_id=message.message_id,
                        job_id=message.job_id,
                        reclaimed=True,
                    )
                )

    @property
    def available_count(self) -> int:
        with self._lock:
            return len(self._available)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
