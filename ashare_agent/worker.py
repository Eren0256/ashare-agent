import argparse
import asyncio
import logging
import os
import signal
import socket

from ashare_agent.config import Settings, get_settings
from ashare_agent.queue import JobQueueProtocol, RedisStreamsJobQueue
from ashare_agent.runtime import (
    AShareAgentRuntime,
    AgentRuntimeProtocol,
    AgentWorker,
)
from ashare_agent.storage import (
    AppDatabase,
    ApplicationRepository,
    FileSystemArtifactStore,
)


def create_worker(
    *,
    name: str | None = None,
    settings: Settings | None = None,
    runtime: AgentRuntimeProtocol | None = None,
    queue: JobQueueProtocol | None = None,
) -> AgentWorker:
    settings = settings or get_settings()
    artifact_store = FileSystemArtifactStore(settings.chart_artifact_dir)
    repository = ApplicationRepository(
        AppDatabase(
            settings.database_url,
            create_schema=settings.database_auto_create_schema,
        ),
        artifact_store,
    )
    job_queue = queue or RedisStreamsJobQueue(
        settings.redis_url,
        stream=settings.redis_job_stream,
        consumer_group=settings.redis_job_consumer_group,
        claim_idle_ms=settings.redis_job_claim_idle_ms,
    )
    return AgentWorker(
        repository,
        runtime or AShareAgentRuntime(),
        job_queue,
        consumer_name=name or _default_worker_name(),
        context_limit=settings.conversation_context_limit,
        block_ms=settings.redis_job_block_ms,
    )


async def _run(name: str | None) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)
    await create_worker(name=name).run(stop_event)


def _default_worker_name() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="A-Share Agent worker")
    parser.add_argument("--name", help="Redis consumer name")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run(args.name))


if __name__ == "__main__":
    main()
