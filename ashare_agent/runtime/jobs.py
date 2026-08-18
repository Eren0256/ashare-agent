import asyncio

from ashare_agent.storage import (
    ApplicationRepository,
    JobRecord,
    SubmittedTurn,
)

from .agent import AgentRuntimeProtocol


class AgentJobService:
    def __init__(
        self,
        repository: ApplicationRepository,
        runtime: AgentRuntimeProtocol,
        *,
        max_concurrency: int = 4,
        context_limit: int = 6,
    ):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if context_limit < 0:
            raise ValueError("context_limit cannot be negative")

        self._repository = repository
        self._runtime = runtime
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._context_limit = context_limit
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self) -> None:
        await self._repository.fail_unfinished_jobs()

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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
            context_limit=self._context_limit,
        )
        task = asyncio.create_task(
            self._run(submitted),
            name=f"agent-job-{submitted.job.id}",
        )
        self._tasks[submitted.job.id] = task
        task.add_done_callback(lambda _: self._tasks.pop(submitted.job.id, None))
        return submitted

    async def get_job(
        self,
        user_id: str,
        job_id: str,
    ) -> JobRecord | None:
        return await self._repository.get_job(user_id, job_id)

    async def _run(self, submitted: SubmittedTurn) -> None:
        job_id = submitted.job.id
        try:
            async with self._semaphore:
                await self._repository.mark_job_running(job_id)
                response = await self._runtime.run(
                    submitted.job.question,
                    submitted.context,
                )
                await self._repository.complete_job(
                    job_id,
                    response.text,
                    response.artifacts,
                )
        except asyncio.CancelledError:
            await self._repository.fail_job(
                job_id,
                RuntimeError("服务正在关闭，任务已终止。"),
            )
            raise
        except Exception as exc:
            await self._repository.fail_job(job_id, exc)
