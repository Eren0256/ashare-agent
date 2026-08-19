import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from ashare_agent.agent import AgentResponse
from ashare_agent.queue import RedisStreamsJobQueue
from ashare_agent.runtime import AgentWorker, JobSubmissionService
from ashare_agent.storage import (
    AppDatabase,
    ApplicationRepository,
    JobStatus,
    SessionBusyError,
)

POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
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
    not POSTGRES_TEST_URL or not REDIS_TEST_URL,
    reason="set POSTGRES_TEST_URL and REDIS_TEST_URL for integration testing",
)
def test_api_and_two_workers_share_postgres_and_redis_state():
    async def scenario() -> None:
        databases = [AppDatabase(POSTGRES_TEST_URL or "") for _ in range(4)]
        repositories = [ApplicationRepository(database) for database in databases]
        stream = f"ashare-agent:test:{uuid4().hex}"
        group = "test-workers"
        queues = [
            RedisStreamsJobQueue(
                REDIS_TEST_URL or "",
                stream=stream,
                consumer_group=group,
                claim_idle_ms=1_000,
            )
            for _ in range(4)
        ]
        redis_cleanup = Redis.from_url(REDIS_TEST_URL or "", decode_responses=True)
        try:
            await asyncio.gather(*(repository.initialize() for repository in repositories))
            async with databases[0].transaction() as connection:
                await connection.execute(text("TRUNCATE TABLE users CASCADE"))
            await asyncio.gather(*(queue.start() for queue in queues))

            api_repository = repositories[0]
            user = await api_repository.create_user("alice", "Alice", "hash")
            sessions = [
                await api_repository.create_session(user.id) for _ in range(2)
            ]
            submissions = JobSubmissionService(api_repository, queues[0])
            submitted = [
                await submissions.submit(user.id, session.id, f"问题{index}")
                for index, session in enumerate(sessions, start=1)
            ]

            runtimes = [EchoRuntime(), EchoRuntime()]
            workers = [
                AgentWorker(
                    repositories[index + 1],
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
                await api_repository.get_job(user.id, item.job.id)
                for item in submitted
            ]
            assert all(item is not None for item in completed)
            assert all(
                item.status == JobStatus.SUCCEEDED for item in completed if item
            )
            assert sum(len(runtime.calls) for runtime in runtimes) == 2

            contested_session = await api_repository.create_session(user.id)
            competing_services = [
                JobSubmissionService(repositories[0], queues[0]),
                JobSubmissionService(repositories[3], queues[3]),
            ]
            results = await asyncio.gather(
                *(
                    service.submit(
                        user.id,
                        contested_session.id,
                        f"竞争问题{index}",
                    )
                    for index, service in enumerate(competing_services, start=1)
                ),
                return_exceptions=True,
            )
            assert sum(isinstance(item, SessionBusyError) for item in results) == 1
            assert sum(not isinstance(item, Exception) for item in results) == 1
        finally:
            await redis_cleanup.delete(stream)
            await asyncio.gather(*(queue.close() for queue in queues))
            await asyncio.gather(*(repository.close() for repository in repositories))
            await redis_cleanup.aclose()

    asyncio.run(scenario())
