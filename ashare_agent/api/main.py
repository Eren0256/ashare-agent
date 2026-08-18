from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from ashare_agent.auth import (
    AuthenticatedUser,
    AuthenticationError,
)
from ashare_agent.storage import (
    JobRecord,
    JobStatus,
    SessionBusyError,
    SessionNotFoundError,
)

from .container import AppContainer, create_container
from .schemas import CreateMessageRequest, LoginRequest


def create_app(
    container: AppContainer | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_container = container or create_container()
        app.state.container = active_container
        await active_container.start()
        try:
            yield
        finally:
            await active_container.shutdown()

    app = FastAPI(
        title="A-Share Analysis Agent API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def api_info() -> dict[str, str]:
        return {
            "service": "A-Share Analysis Agent API",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/login")
    async def login(
        payload: LoginRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            token, user = await _container(request).auth.login(
                payload.username,
                payload.password,
            )
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user.model_dump(mode="json"),
        }

    @app.get("/auth/me")
    async def me(
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, Any]:
        return user.model_dump(mode="json")

    @app.get("/sessions")
    async def list_sessions(
        request: Request,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = Query(default=None),
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, Any]:
        try:
            page = await _container(request).repository.list_sessions(
                user.id,
                limit=limit,
                cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="cursor无效。") from exc
        return {
            "items": [item.model_dump(mode="json") for item in page["items"]],
            "next_cursor": page["next_cursor"],
        }

    @app.post("/sessions", status_code=201)
    async def create_session(
        request: Request,
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, Any]:
        session = await _container(request).repository.create_session(user.id)
        return session.model_dump(mode="json")

    @app.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        request: Request,
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, str]:
        try:
            deleted = await _container(request).repository.delete_session(
                user.id,
                session_id,
            )
        except SessionBusyError as exc:
            raise HTTPException(
                status_code=409,
                detail="当前会话任务执行中，暂时不能删除。",
            ) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在。")
        return {"status": "deleted"}

    @app.get("/sessions/{session_id}/messages")
    async def list_messages(
        session_id: str,
        request: Request,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = Query(default=None),
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, Any]:
        try:
            page = await _container(request).repository.list_messages(
                user.id,
                session_id,
                limit=limit,
                cursor=cursor,
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="会话不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="cursor无效。") from exc
        return {
            "items": [item.model_dump(mode="json") for item in page["items"]],
            "next_cursor": page["next_cursor"],
        }

    @app.post("/sessions/{session_id}/messages", status_code=202)
    async def create_message(
        session_id: str,
        payload: CreateMessageRequest,
        request: Request,
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, Any]:
        try:
            submitted = await _container(request).jobs.submit(
                user.id,
                session_id,
                payload.query,
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="会话不存在。") from exc
        except SessionBusyError as exc:
            raise HTTPException(
                status_code=409,
                detail="当前会话已有任务正在执行。",
            ) from exc
        return {
            "job_id": submitted.job.id,
            "status": submitted.job.status.value,
            "created_at": submitted.job.created_at,
            "user_message": submitted.user_message.model_dump(mode="json"),
        }

    @app.get("/jobs/{job_id}")
    async def get_job(
        job_id: str,
        request: Request,
        user: AuthenticatedUser = Depends(_current_user),
    ) -> dict[str, Any]:
        job = await _container(request).jobs.get_job(user.id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return _public_job(job)

    @app.get("/artifacts/{artifact_id}")
    async def get_artifact(
        artifact_id: str,
        request: Request,
        user: AuthenticatedUser = Depends(_current_user),
    ) -> FileResponse:
        artifact = await _container(request).repository.get_artifact(
            user.id,
            artifact_id,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="图片不存在。")
        path = Path(artifact.file_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="图片文件不存在。")
        return FileResponse(
            path,
            media_type=artifact.mime_type,
            filename=path.name,
        )

    return app


async def _current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录。")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="认证格式应为Bearer token。")
    try:
        return await _container(request).auth.authenticate(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _container(request: Request) -> AppContainer:
    return request.app.state.container


def _public_job(job: JobRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job.id,
        "session_id": job.session_id,
        "status": job.status.value,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error": job.error,
        "error_type": job.error_type,
    }
    if job.status == JobStatus.SUCCEEDED:
        payload["result"] = {
            "reply": job.result_text or "",
            "artifacts": [artifact.public_dict() for artifact in job.artifacts],
        }
    return payload


app = create_app()
