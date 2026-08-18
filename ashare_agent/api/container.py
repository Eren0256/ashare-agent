from dataclasses import dataclass

from ashare_agent.auth import AuthService
from ashare_agent.config import Settings, get_settings
from ashare_agent.runtime import (
    AShareAgentRuntime,
    AgentJobService,
    AgentRuntimeProtocol,
)
from ashare_agent.storage import AppDatabase, ApplicationRepository


@dataclass
class AppContainer:
    repository: ApplicationRepository
    auth: AuthService
    jobs: AgentJobService

    async def start(self) -> None:
        await self.auth.initialize()
        await self.jobs.start()

    async def shutdown(self) -> None:
        await self.jobs.shutdown()


def create_container(
    settings: Settings | None = None,
    runtime: AgentRuntimeProtocol | None = None,
) -> AppContainer:
    settings = settings or get_settings()
    repository = ApplicationRepository(AppDatabase(settings.app_db_path))
    auth = AuthService(
        repository,
        secret=settings.app_jwt_secret.get_secret_value(),
        expire_hours=settings.app_jwt_expire_hours,
        demo_username=settings.demo_username,
        demo_password=settings.demo_password.get_secret_value(),
        demo_display_name=settings.demo_display_name,
    )
    jobs = AgentJobService(
        repository,
        runtime or AShareAgentRuntime(),
        max_concurrency=settings.app_job_max_concurrency,
        context_limit=settings.conversation_context_limit,
    )
    return AppContainer(
        repository=repository,
        auth=auth,
        jobs=jobs,
    )
