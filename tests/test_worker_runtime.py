import asyncio

import pytest

from ashare_agent.agent import AgentResponse
from ashare_agent.runtime import AgentWorker, JobSubmissionService
from ashare_agent.storage import (
    ApplicationRepository,
    JobStatus,
)
from tests.support import MemoryJobQueue, sqlite_test_database


class StaticRuntime:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse:
        self.calls.append((question, context))
        await asyncio.sleep(0)
        return AgentResponse(text=self.answer)


class CancelledRuntime:
    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse:
        del question, context
        raise asyncio.CancelledError


class FailedRuntime:
    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse:
        del question, context
        raise ValueError("agent failed")


class RecoverableQueue(MemoryJobQueue):
    def __init__(self) -> None:
        super().__init__()
        self.available = False

    async def start(self) -> None:
        if not self.available:
            raise ConnectionError("redis unavailable")


async def _create_session(
    repository: ApplicationRepository,
    username: str,
):
    user = await repository.create_user(username, username, "hash")
    session = await repository.create_session(user.id)
    return user, session


def test_job_stays_queued_until_worker_consumes_it(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = MemoryJobQueue()
        user, session = await _create_session(repository, "alice")
        submissions = JobSubmissionService(repository, queue)
        submitted = await submissions.submit(user.id, session.id, "问题")

        queued = await repository.get_job(user.id, submitted.job.id)
        assert queued is not None
        assert queued.status == JobStatus.QUEUED

        runtime = StaticRuntime("回答")
        worker = AgentWorker(
            repository,
            runtime,
            queue,
            consumer_name="worker-1",
            block_ms=0,
        )
        assert await worker.process_next() is True

        succeeded = await repository.get_job(user.id, submitted.job.id)
        assert succeeded is not None
        assert succeeded.status == JobStatus.SUCCEEDED
        assert succeeded.result_text == "回答"
        assert len(runtime.calls) == 1
        assert queue.pending_count == 0

    asyncio.run(scenario())


def test_worker_unregisters_consumer_during_graceful_shutdown(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = MemoryJobQueue()
        worker = AgentWorker(
            repository,
            StaticRuntime("回答"),
            queue,
            consumer_name="worker-terminating",
            block_ms=0,
        )
        stop_event = asyncio.Event()
        stop_event.set()

        await worker.run(stop_event)

        assert queue.unregistered_consumers == ["worker-terminating"]

    asyncio.run(scenario())


def test_two_workers_compete_without_duplicate_execution(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = MemoryJobQueue()
        user, first_session = await _create_session(repository, "alice")
        second_session = await repository.create_session(user.id)
        submissions = JobSubmissionService(repository, queue)
        first = await submissions.submit(user.id, first_session.id, "问题一")
        second = await submissions.submit(user.id, second_session.id, "问题二")

        first_runtime = StaticRuntime("回答一")
        second_runtime = StaticRuntime("回答二")
        workers = [
            AgentWorker(
                repository,
                first_runtime,
                queue,
                consumer_name="worker-1",
                block_ms=0,
            ),
            AgentWorker(
                repository,
                second_runtime,
                queue,
                consumer_name="worker-2",
                block_ms=0,
            ),
        ]
        assert await asyncio.gather(*(item.process_next() for item in workers)) == [
            True,
            True,
        ]

        jobs = [
            await repository.get_job(user.id, first.job.id),
            await repository.get_job(user.id, second.job.id),
        ]
        assert all(item is not None for item in jobs)
        assert all(item.status == JobStatus.SUCCEEDED for item in jobs if item)
        assert len(first_runtime.calls) + len(second_runtime.calls) == 2
        assert queue.pending_count == 0

    asyncio.run(scenario())


def test_duplicate_message_does_not_execute_completed_job_twice(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = MemoryJobQueue()
        user, session = await _create_session(repository, "alice")
        submissions = JobSubmissionService(repository, queue)
        submitted = await submissions.submit(user.id, session.id, "问题")
        await queue.publish(submitted.job.id)

        runtime = StaticRuntime("回答")
        workers = [
            AgentWorker(
                repository,
                runtime,
                queue,
                consumer_name=f"worker-{index}",
                block_ms=0,
            )
            for index in range(2)
        ]
        await asyncio.gather(*(item.process_next() for item in workers))

        job = await repository.get_job(user.id, submitted.job.id)
        assert job is not None
        assert job.status == JobStatus.SUCCEEDED
        assert len(runtime.calls) == 1
        assert len(queue.acknowledged) == 2

    asyncio.run(scenario())


def test_reclaimed_message_resumes_job_after_worker_stops(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = MemoryJobQueue()
        user, session = await _create_session(repository, "alice")
        submissions = JobSubmissionService(repository, queue)
        submitted = await submissions.submit(user.id, session.id, "问题")

        stopped_worker = AgentWorker(
            repository,
            CancelledRuntime(),
            queue,
            consumer_name="worker-stopped",
            block_ms=0,
        )
        with pytest.raises(asyncio.CancelledError):
            await stopped_worker.process_next()
        interrupted = await repository.get_job(user.id, submitted.job.id)
        assert interrupted is not None
        assert interrupted.status == JobStatus.RUNNING
        assert queue.pending_count == 1

        queue.redeliver_pending()
        recovery_runtime = StaticRuntime("恢复后的回答")
        recovery_worker = AgentWorker(
            repository,
            recovery_runtime,
            queue,
            consumer_name="worker-recovery",
            block_ms=0,
        )
        assert await recovery_worker.process_next() is True

        recovered = await repository.get_job(user.id, submitted.job.id)
        assert recovered is not None
        assert recovered.status == JobStatus.SUCCEEDED
        assert recovered.result_text == "恢复后的回答"
        assert queue.pending_count == 0

    asyncio.run(scenario())


def test_agent_error_marks_job_failed_and_acknowledges_message(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = MemoryJobQueue()
        user, session = await _create_session(repository, "alice")
        submissions = JobSubmissionService(repository, queue)
        submitted = await submissions.submit(user.id, session.id, "问题")
        worker = AgentWorker(
            repository,
            FailedRuntime(),
            queue,
            consumer_name="worker-1",
            block_ms=0,
        )

        assert await worker.process_next() is True
        failed = await repository.get_job(user.id, submitted.job.id)
        assert failed is not None
        assert failed.status == JobStatus.FAILED
        assert failed.error_type == "ValueError"
        assert failed.error == "agent failed"
        assert queue.pending_count == 0

    asyncio.run(scenario())


def test_transactional_outbox_dispatches_after_queue_recovers(tmp_path):
    async def scenario() -> None:
        repository = ApplicationRepository(
            sqlite_test_database(tmp_path / "app.sqlite3")
        )
        queue = RecoverableQueue()
        user, session = await _create_session(repository, "alice")
        submissions = JobSubmissionService(repository, queue)

        submitted = await submissions.submit(user.id, session.id, "问题")
        durable = await repository.get_job(user.id, submitted.job.id)
        assert durable is not None
        assert durable.status == JobStatus.QUEUED
        assert queue.available_count == 0

        queue.available = True
        assert await submissions.dispatch_pending() == 1
        assert await submissions.dispatch_pending() == 0
        assert queue.available_count == 1

        runtime = StaticRuntime("回答")
        worker = AgentWorker(
            repository,
            runtime,
            queue,
            consumer_name="worker-1",
            block_ms=0,
        )
        assert await worker.process_next() is True
        completed = await repository.get_job(user.id, submitted.job.id)
        assert completed is not None
        assert completed.status == JobStatus.SUCCEEDED

    asyncio.run(scenario())
