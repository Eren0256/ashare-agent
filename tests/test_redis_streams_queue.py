import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from ashare_agent.agent import AgentResponse
from ashare_agent.queue import RedisStreamsJobQueue
from ashare_agent.runtime import AgentWorker, JobSubmissionService
from ashare_agent.storage import ApplicationRepository, JobStatus
from tests.support import sqlite_test_database

REDIS_TEST_URL = os.getenv("REDIS_TEST_URL")


class EchoRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(
        self,
        question: str,
        context: list[dict[str, str]],
    ) -> AgentResponse:
        del context
        self.calls.append(question)
        await asyncio.sleep(0.01)
        return AgentResponse(text=f"回答：{question}")


@pytest.mark.skipif(
    not REDIS_TEST_URL,
    reason="set REDIS_TEST_URL to run the Redis integration test",
)
def test_redis_streams_distributes_and_reclaims_jobs():
    async def scenario() -> None:
        stream = f"ashare-agent:test:{uuid4().hex}"
        group = "test-workers"
        queues = [
            RedisStreamsJobQueue(
                REDIS_TEST_URL or "",
                stream=stream,
                consumer_group=group,
                claim_idle_ms=10,
            )
            for _ in range(2)
        ]
        cleanup = Redis.from_url(REDIS_TEST_URL or "", decode_responses=True)
        try:
            await asyncio.gather(*(queue.start() for queue in queues))
            await queues[0].publish("job-1")
            await queues[0].publish("job-2")

            received = await asyncio.gather(
                queues[0].receive("worker-1", block_ms=100),
                queues[1].receive("worker-2", block_ms=100),
            )
            assert {item.job_id for item in received if item} == {
                "job-1",
                "job-2",
            }
            await asyncio.gather(
                *(
                    queue.acknowledge(item.message_id)
                    for queue, item in zip(queues, received, strict=True)
                    if item
                )
            )

            await queues[0].publish("job-recovery")
            interrupted = await queues[0].receive("worker-1", block_ms=100)
            assert interrupted is not None
            await asyncio.sleep(0.02)
            reclaimed = await queues[1].receive("worker-2", block_ms=100)
            assert reclaimed is not None
            assert reclaimed.job_id == "job-recovery"
            assert reclaimed.reclaimed is True
            await queues[1].acknowledge(reclaimed.message_id)
            assert await cleanup.xlen(stream) == 0
        finally:
            await cleanup.delete(stream)
            await asyncio.gather(*(queue.close() for queue in queues))
            await cleanup.aclose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not REDIS_TEST_URL,
    reason="set REDIS_TEST_URL to run the Redis integration test",
)
def test_two_agent_workers_consume_real_redis_stream(tmp_path):
    async def scenario() -> None:
        stream = f"ashare-agent:test:{uuid4().hex}"
        group = "test-workers"
        queues = [
            RedisStreamsJobQueue(
                REDIS_TEST_URL or "",
                stream=stream,
                consumer_group=group,
                claim_idle_ms=1_000,
            )
            for _ in range(3)
        ]
        cleanup = Redis.from_url(REDIS_TEST_URL or "", decode_responses=True)
        database_path = tmp_path / "app.sqlite3"
        api_repository = ApplicationRepository(sqlite_test_database(database_path))
        worker_repositories = [
            ApplicationRepository(sqlite_test_database(database_path))
            for _ in range(2)
        ]
        runtimes = [EchoRuntime(), EchoRuntime()]
        try:
            await asyncio.gather(*(queue.start() for queue in queues))
            user = await api_repository.create_user("alice", "Alice", "hash")
            sessions = [
                await api_repository.create_session(user.id) for _ in range(2)
            ]
            submissions = JobSubmissionService(api_repository, queues[0])
            jobs = [
                await submissions.submit(user.id, session.id, f"问题{index}")
                for index, session in enumerate(sessions, start=1)
            ]
            workers = [
                AgentWorker(
                    worker_repositories[index],
                    runtimes[index],
                    queues[index + 1],
                    consumer_name=f"worker-{index + 1}",
                    block_ms=100,
                )
                for index in range(2)
            ]

            assert await asyncio.gather(
                *(worker.process_next() for worker in workers)
            ) == [True, True]
            completed = [
                await api_repository.get_job(user.id, item.job.id) for item in jobs
            ]
            assert all(item is not None for item in completed)
            assert all(
                item.status == JobStatus.SUCCEEDED for item in completed if item
            )
            assert sum(len(runtime.calls) for runtime in runtimes) == 2
            assert await cleanup.xlen(stream) == 0
        finally:
            await cleanup.delete(stream)
            await asyncio.gather(*(queue.close() for queue in queues))
            await cleanup.aclose()

    asyncio.run(scenario())
