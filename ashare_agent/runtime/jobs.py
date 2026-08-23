import asyncio
import logging

from ashare_agent.queue import JobQueueProtocol, QueuedJob
from ashare_agent.storage import (
    ApplicationRepository,
    JobRecord,
    SubmittedTurn,
)

from .agent import AgentRuntimeProtocol

logger = logging.getLogger(__name__)


class JobSubmissionService:
    def __init__(
        self,
        repository: ApplicationRepository,
        queue: JobQueueProtocol,
        *,
        dispatch_interval_seconds: float = 1.0,
    ) -> None:
        if dispatch_interval_seconds <= 0:
            raise ValueError("dispatch_interval_seconds must be positive")
        self._repository = repository
        self._queue = queue
        self._dispatch_interval_seconds = dispatch_interval_seconds
        self._dispatcher_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            await self._queue.start()
        except Exception:
            logger.exception("Job queue is unavailable; outbox retry will continue")
        self._dispatcher_task = asyncio.create_task(
            self._dispatch_loop(),
            name="job-outbox-dispatcher",
        )

    async def shutdown(self) -> None:
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            await asyncio.gather(self._dispatcher_task, return_exceptions=True)
            self._dispatcher_task = None
        await self._queue.close()

    async def submit(
        self,
        user_id: str,
        session_id: str,
        question: str,
    ) -> SubmittedTurn:
        submitted = await self._repository.submit_turn(
            user_id,
            session_id,
            question,
        )
        try:
            await self._publish(submitted.job.id)
        except Exception:
            logger.exception(
                "Job %s is durable but waiting for outbox dispatch",
                submitted.job.id,
            )
        return submitted

    async def dispatch_pending(self) -> int:
        dispatched = 0
        job_ids = await self._repository.list_pending_job_dispatches()
        for job_id in job_ids:
            await self._publish(job_id)
            dispatched += 1
        return dispatched

    async def _publish(self, job_id: str) -> None:
        await self._queue.start()
        message_id = await self._queue.publish(job_id)
        await self._repository.mark_job_dispatched(job_id, message_id)

    async def _dispatch_loop(self) -> None:
        while True:
            try:
                await self.dispatch_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to dispatch PostgreSQL outbox")
            await asyncio.sleep(self._dispatch_interval_seconds)

    async def get_job(
        self,
        user_id: str,
        job_id: str,
    ) -> JobRecord | None:
        return await self._repository.get_job(user_id, job_id)


class AgentWorker:
    def __init__(
        self,
        repository: ApplicationRepository,
        runtime: AgentRuntimeProtocol,
        queue: JobQueueProtocol,
        *,
        consumer_name: str,
        context_limit: int = 6,
        block_ms: int = 1_000,
    ) -> None:
        if not consumer_name:
            raise ValueError("consumer_name cannot be empty")
        if context_limit < 0:
            raise ValueError("context_limit cannot be negative")
        if block_ms < 0:
            raise ValueError("block_ms cannot be negative")
        self._repository = repository
        self._runtime = runtime
        self._queue = queue
        self._consumer_name = consumer_name
        self._context_limit = context_limit
        self._block_ms = block_ms

    async def start(self) -> None:
        await self._repository.initialize()
        await self._queue.start()

    async def shutdown(self) -> None:
        try:
            await self._queue.unregister_consumer(self._consumer_name)
        except Exception:
            logger.warning(
                "Failed to unregister worker %s",
                self._consumer_name,
                exc_info=True,
            )
        finally:
            try:
                await self._queue.close()
            finally:
                await self._repository.close()

    async def run(self, stop_event: asyncio.Event) -> None:
        await self.start()
        logger.info("Agent worker %s started", self._consumer_name)
        try:
            while not stop_event.is_set():
                await self.process_next()
        finally:
            await self.shutdown()
            logger.info("Agent worker %s stopped", self._consumer_name)

    async def process_next(self) -> bool:
        queued_job = await self._queue.receive(
            self._consumer_name,
            block_ms=self._block_ms,
        )
        if queued_job is None:
            return False
        await self._process(queued_job)
        return True

    async def _process(self, queued_job: QueuedJob) -> None:
        if not queued_job.job_id:
            logger.error(
                "Discarding malformed queue message %s",
                queued_job.message_id,
            )
            await self._queue.acknowledge(queued_job.message_id)
            return

        try:
            submitted = await self._repository.claim_job(
                queued_job.job_id,
                context_limit=self._context_limit,
                allow_running=queued_job.reclaimed,
            )
        except KeyError:
            logger.error("Discarding unknown job %s", queued_job.job_id)
            await self._queue.acknowledge(queued_job.message_id)
            return

        if submitted is None:
            await self._queue.acknowledge(queued_job.message_id)
            return

        try:
            response = await self._runtime.run(
                submitted.job.question,
                submitted.context,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._repository.fail_job(submitted.job.id, exc)
        else:
            await self._repository.complete_job(
                submitted.job.id,
                response.text,
                response.artifacts,
            )
        await self._queue.acknowledge(queued_job.message_id)
