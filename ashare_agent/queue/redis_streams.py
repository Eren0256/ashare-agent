from redis.asyncio import Redis
from redis.exceptions import ResponseError

from .base import QueuedJob


class RedisStreamsJobQueue:
    def __init__(
        self,
        url: str,
        *,
        stream: str,
        consumer_group: str,
        claim_idle_ms: int,
    ) -> None:
        if claim_idle_ms < 1:
            raise ValueError("claim_idle_ms must be positive")
        self._client = Redis.from_url(url, decode_responses=True)
        self._stream = stream
        self._consumer_group = consumer_group
        self._claim_idle_ms = claim_idle_ms
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self._client.ping()
        try:
            await self._client.xgroup_create(
                self._stream,
                self._consumer_group,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._started = True

    async def publish(self, job_id: str) -> str:
        if not job_id:
            raise ValueError("job_id cannot be empty")
        return await self._client.xadd(self._stream, {"job_id": job_id})

    async def receive(
        self,
        consumer_name: str,
        *,
        block_ms: int,
    ) -> QueuedJob | None:
        if not consumer_name:
            raise ValueError("consumer_name cannot be empty")
        if block_ms < 0:
            raise ValueError("block_ms cannot be negative")

        claimed = await self._client.xautoclaim(
            self._stream,
            self._consumer_group,
            consumer_name,
            min_idle_time=self._claim_idle_ms,
            start_id="0-0",
            count=1,
        )
        if claimed[1]:
            return _queued_job(claimed[1][0], reclaimed=True)

        response = await self._client.xreadgroup(
            self._consumer_group,
            consumer_name,
            {self._stream: ">"},
            count=1,
            block=block_ms,
        )
        if not response:
            return None
        return _queued_job(response[0][1][0], reclaimed=False)

    async def acknowledge(self, message_id: str) -> None:
        await self._client.xack(
            self._stream,
            self._consumer_group,
            message_id,
        )
        await self._client.xdel(self._stream, message_id)

    async def unregister_consumer(self, consumer_name: str) -> None:
        if not consumer_name:
            raise ValueError("consumer_name cannot be empty")
        await self._client.xgroup_delconsumer(
            self._stream,
            self._consumer_group,
            consumer_name,
        )

    async def close(self) -> None:
        await self._client.aclose()
        self._started = False


def _queued_job(
    message: tuple[str, dict[str, str]],
    *,
    reclaimed: bool,
) -> QueuedJob:
    message_id, fields = message
    return QueuedJob(
        message_id=message_id,
        job_id=fields.get("job_id", ""),
        reclaimed=reclaimed,
    )
