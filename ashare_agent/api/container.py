from dataclasses import dataclass

from ashare_agent.auth import AuthService
from ashare_agent.config import Settings, get_settings
from ashare_agent.queue import JobQueueProtocol, RedisStreamsJobQueue
from ashare_agent.runtime import (
    JobSubmissionService,
)
from ashare_agent.storage import (
    AppDatabase,
    ApplicationRepository,
    FileSystemArtifactStore,
)


@dataclass
class AppContainer:
    repository: ApplicationRepository
    artifacts: FileSystemArtifactStore
    auth: AuthService
    jobs: JobSubmissionService

    async def start(self) -> None:
        await self.repository.initialize()
        await self.auth.initialize()
        await self.jobs.start()

    async def shutdown(self) -> None:
        await self.jobs.shutdown()
        await self.repository.close()


def create_container(
    settings: Settings | None = None,
    queue: JobQueueProtocol | None = None,
) -> AppContainer:
    settings = settings or get_settings()
    artifact_store = FileSystemArtifactStore(settings.chart_artifact_dir)
    repository = ApplicationRepository(
        AppDatabase(
            settings.database_url,
            create_schema=settings.database_auto_create_schema,
        ),
        artifact_store,
    )
    auth = AuthService(
        repository,
        secret=settings.app_jwt_secret.get_secret_value(),
        expire_hours=settings.app_jwt_expire_hours,
        demo_username=settings.demo_username,
        demo_password=settings.demo_password.get_secret_value(),
        demo_display_name=settings.demo_display_name,
    )
    job_queue = queue or RedisStreamsJobQueue(
        settings.redis_url,
        stream=settings.redis_job_stream,
        consumer_group=settings.redis_job_consumer_group,
        claim_idle_ms=settings.redis_job_claim_idle_ms,
    )
    jobs = JobSubmissionService(
        repository,
        job_queue,
        dispatch_interval_seconds=settings.job_outbox_dispatch_interval_seconds,
    )
    return AppContainer(
        repository=repository,
        artifacts=artifact_store,
        auth=auth,
        jobs=jobs,
    )
