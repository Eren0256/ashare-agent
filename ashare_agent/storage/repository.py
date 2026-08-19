import base64
from collections.abc import Mapping
from datetime import UTC, datetime
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ashare_agent.domain import ChartArtifact

from .artifact_store import FileSystemArtifactStore
from .database import AppDatabase
from .models import (
    ArtifactRecord,
    JobRecord,
    JobStatus,
    MessageRecord,
    SessionRecord,
    SubmittedTurn,
    UserRecord,
)
from .schema import artifacts, job_outbox, jobs, messages, sessions, users


class SessionNotFoundError(LookupError):
    pass


class SessionBusyError(RuntimeError):
    pass


class ApplicationRepository:
    def __init__(
        self,
        database: AppDatabase,
        artifact_store: FileSystemArtifactStore | None = None,
    ):
        self.database = database
        self.artifact_store = artifact_store or FileSystemArtifactStore(
            ".artifacts/charts"
        )

    async def initialize(self) -> None:
        await self.database.initialize()

    async def close(self) -> None:
        await self.database.close()

    async def create_user(
        self,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> UserRecord:
        user = UserRecord(
            id=uuid4().hex,
            username=username,
            display_name=display_name,
            password_hash=password_hash,
        )
        try:
            async with self.database.transaction() as connection:
                existing = (
                    await connection.execute(
                        select(users).where(users.c.username == username)
                    )
                ).mappings().first()
                if existing is not None:
                    return _user(existing)
                await connection.execute(
                    insert(users).values(
                        id=user.id,
                        username=user.username,
                        display_name=user.display_name,
                        password_hash=user.password_hash,
                        is_active=True,
                        created_at=_now(),
                    )
                )
                return user
        except IntegrityError:
            async with self.database.transaction() as connection:
                existing = (
                    await connection.execute(
                        select(users).where(users.c.username == username)
                    )
                ).mappings().first()
                if existing is not None:
                    return _user(existing)
            raise

    async def get_user_by_username(
        self,
        username: str,
    ) -> UserRecord | None:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(
                    select(users).where(users.c.username == username)
                )
            ).mappings().first()
            return _optional_user(row)

    async def get_user_by_id(
        self,
        user_id: str,
    ) -> UserRecord | None:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(select(users).where(users.c.id == user_id))
            ).mappings().first()
            return _optional_user(row)

    async def create_session(
        self,
        user_id: str,
    ) -> SessionRecord:
        now = _now()
        session = SessionRecord(
            id=uuid4().hex,
            user_id=user_id,
            title="新对话",
            created_at=now,
            updated_at=now,
        )
        async with self.database.transaction() as connection:
            await connection.execute(insert(sessions).values(**session.model_dump()))
        return session

    async def get_session(
        self,
        user_id: str,
        session_id: str,
    ) -> SessionRecord | None:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(
                    select(sessions).where(
                        sessions.c.id == session_id,
                        sessions.c.user_id == user_id,
                    )
                )
            ).mappings().first()
            return _optional_session(row)

    async def delete_session(
        self,
        user_id: str,
        session_id: str,
    ) -> bool:
        async with self.database.transaction() as connection:
            session_row = (
                await connection.execute(
                    select(sessions.c.id)
                    .where(
                        sessions.c.id == session_id,
                        sessions.c.user_id == user_id,
                    )
                    .with_for_update()
                )
            ).first()
            if session_row is None:
                return False
            active_job = (
                await connection.execute(
                    select(jobs.c.id)
                    .where(
                        jobs.c.session_id == session_id,
                        jobs.c.user_id == user_id,
                        jobs.c.status.in_(["queued", "running"]),
                    )
                    .limit(1)
                )
            ).first()
            if active_job is not None:
                raise SessionBusyError(session_id)
            result = await connection.execute(
                delete(sessions).where(
                    sessions.c.id == session_id,
                    sessions.c.user_id == user_id,
                )
            )
            return result.rowcount > 0

    async def list_sessions(
        self,
        user_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 50))
        statement = select(sessions).where(sessions.c.user_id == user_id)
        if cursor:
            updated_at, session_id = _decode_cursor(cursor)
            statement = statement.where(
                or_(
                    sessions.c.updated_at < updated_at,
                    (sessions.c.updated_at == updated_at) & (sessions.c.id < session_id),
                )
            )
        statement = statement.order_by(
            sessions.c.updated_at.desc(),
            sessions.c.id.desc(),
        ).limit(limit + 1)
        async with self.database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        items = [_session(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.updated_at, last.id)
        return {"items": items, "next_cursor": next_cursor}

    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 50))
        async with self.database.transaction() as connection:
            await _require_session(connection, user_id, session_id)
            statement = select(messages).where(
                messages.c.session_id == session_id,
                messages.c.user_id == user_id,
            )
            if cursor:
                created_at, message_id = _decode_cursor(cursor)
                statement = statement.where(
                    or_(
                        messages.c.created_at < created_at,
                        (messages.c.created_at == created_at)
                        & (messages.c.id < message_id),
                    )
                )
            statement = statement.order_by(
                messages.c.created_at.desc(),
                messages.c.id.desc(),
            ).limit(limit + 1)
            rows = (await connection.execute(statement)).mappings().all()
        newest = [_message(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit and newest:
            last = newest[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)
        return {
            "items": list(reversed(newest)),
            "next_cursor": next_cursor,
        }

    async def submit_turn(
        self,
        user_id: str,
        session_id: str,
        question: str,
    ) -> SubmittedTurn:
        question = question.strip()
        if not question:
            raise ValueError("question cannot be empty")
        now = _now()
        message = MessageRecord(
            id=uuid4().hex,
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=question,
            created_at=now,
        )
        job = JobRecord(
            id=uuid4().hex,
            session_id=session_id,
            user_id=user_id,
            user_message_id=message.id,
            status=JobStatus.QUEUED,
            question=question,
            created_at=now,
        )
        try:
            async with self.database.transaction() as connection:
                session = await _require_session(
                    connection,
                    user_id,
                    session_id,
                    for_update=True,
                )
                active_job = (
                    await connection.execute(
                        select(jobs.c.id)
                        .where(
                            jobs.c.session_id == session_id,
                            jobs.c.user_id == user_id,
                            jobs.c.status.in_(["queued", "running"]),
                        )
                        .limit(1)
                    )
                ).first()
                if active_job is not None:
                    raise SessionBusyError(session_id)
                await connection.execute(
                    insert(messages).values(
                        id=message.id,
                        session_id=message.session_id,
                        user_id=message.user_id,
                        role=message.role,
                        content=message.content,
                        metadata_json={},
                        created_at=message.created_at,
                    )
                )
                await connection.execute(
                    insert(jobs).values(
                        id=job.id,
                        session_id=job.session_id,
                        user_id=job.user_id,
                        user_message_id=job.user_message_id,
                        status=job.status.value,
                        question=job.question,
                        created_at=job.created_at,
                    )
                )
                await connection.execute(
                    insert(job_outbox).values(
                        id=uuid4().hex,
                        job_id=job.id,
                        created_at=now,
                    )
                )
                title = session.title
                if title == "新对话":
                    title = _session_title(question)
                await connection.execute(
                    update(sessions)
                    .where(
                        sessions.c.id == session_id,
                        sessions.c.user_id == user_id,
                    )
                    .values(title=title, updated_at=now)
                )
        except IntegrityError as exc:
            if "uq_jobs_one_active_per_session" in str(exc):
                raise SessionBusyError(session_id) from exc
            raise
        return SubmittedTurn(job=job, user_message=message)

    async def list_pending_job_dispatches(
        self,
        *,
        limit: int = 100,
    ) -> list[str]:
        limit = max(1, min(limit, 1_000))
        async with self.database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(job_outbox.c.job_id)
                    .where(job_outbox.c.published_at.is_(None))
                    .order_by(job_outbox.c.created_at, job_outbox.c.id)
                    .limit(limit)
                )
            ).all()
            return [row.job_id for row in rows]

    async def mark_job_dispatched(
        self,
        job_id: str,
        broker_message_id: str,
    ) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(
                update(job_outbox)
                .where(
                    job_outbox.c.job_id == job_id,
                    job_outbox.c.published_at.is_(None),
                )
                .values(
                    broker_message_id=broker_message_id,
                    published_at=_now(),
                )
            )

    async def claim_job(
        self,
        job_id: str,
        *,
        context_limit: int,
        allow_running: bool = False,
    ) -> SubmittedTurn | None:
        if context_limit < 0:
            raise ValueError("context_limit cannot be negative")
        async with self.database.transaction() as connection:
            claimed = (
                await connection.execute(
                    update(jobs)
                    .where(jobs.c.id == job_id, jobs.c.status == "queued")
                    .values(status="running", started_at=_now())
                    .returning(jobs)
                )
            ).mappings().first()
            if claimed is None:
                claimed = (
                    await connection.execute(select(jobs).where(jobs.c.id == job_id))
                ).mappings().first()
                if claimed is None:
                    raise KeyError(job_id)
                if claimed["status"] != "running" or not allow_running:
                    return None
            job = _job(claimed)
            message_row = (
                await connection.execute(
                    select(messages).where(messages.c.id == job.user_message_id)
                )
            ).mappings().first()
            if message_row is None:
                raise KeyError(job.user_message_id)
            context_rows = (
                await connection.execute(
                    select(messages)
                    .where(
                        messages.c.session_id == job.session_id,
                        messages.c.user_id == job.user_id,
                        messages.c.id != job.user_message_id,
                    )
                    .order_by(messages.c.created_at.desc(), messages.c.id.desc())
                    .limit(context_limit)
                )
            ).mappings().all()
            context = [
                {"role": item.role, "content": item.content}
                for item in reversed([_message(row) for row in context_rows])
            ]
            return SubmittedTurn(
                job=job,
                user_message=_message(message_row),
                context=context,
            )

    async def complete_job(
        self,
        job_id: str,
        text: str,
        chart_artifacts: list[ChartArtifact],
    ) -> JobRecord:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(
                    select(jobs).where(jobs.c.id == job_id).with_for_update()
                )
            ).mappings().first()
            if row is None:
                raise KeyError(job_id)
            job = _job(row)
            if job.status == JobStatus.SUCCEEDED:
                return await _job_with_artifacts(connection, job)
            if job.status != JobStatus.RUNNING:
                raise RuntimeError(f"Cannot complete job in status {job.status.value}")

            now = _now()
            message_id = uuid4().hex
            records = [
                ArtifactRecord(
                    id=uuid4().hex,
                    source_artifact_id=artifact.artifact_id,
                    job_id=job.id,
                    message_id=message_id,
                    session_id=job.session_id,
                    user_id=job.user_id,
                    title=artifact.title,
                    mime_type=artifact.mime_type,
                    storage_key=self.artifact_store.key_for(artifact.file_path),
                    width=artifact.width,
                    height=artifact.height,
                    chart_type=artifact.chart_type.value,
                    created_at=now,
                )
                for artifact in chart_artifacts
            ]
            metadata_payload = {
                "job_id": job.id,
                "artifacts": [item.public_dict() for item in records],
            }
            await connection.execute(
                insert(messages).values(
                    id=message_id,
                    session_id=job.session_id,
                    user_id=job.user_id,
                    role="assistant",
                    content=text,
                    metadata_json=metadata_payload,
                    created_at=now,
                )
            )
            if records:
                await connection.execute(
                    insert(artifacts),
                    [item.model_dump() for item in records],
                )
            updated = (
                await connection.execute(
                    update(jobs)
                    .where(jobs.c.id == job.id)
                    .values(
                        status="succeeded",
                        result_text=text,
                        assistant_message_id=message_id,
                        completed_at=now,
                    )
                    .returning(jobs)
                )
            ).mappings().one()
            await connection.execute(
                update(sessions)
                .where(
                    sessions.c.id == job.session_id,
                    sessions.c.user_id == job.user_id,
                )
                .values(updated_at=now)
            )
            return _job(updated).model_copy(update={"artifacts": records})

    async def fail_job(
        self,
        job_id: str,
        error: Exception,
    ) -> JobRecord:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(
                    update(jobs)
                    .where(
                        jobs.c.id == job_id,
                        jobs.c.status.in_(["queued", "running"]),
                    )
                    .values(
                        status="failed",
                        error=str(error),
                        error_type=type(error).__name__,
                        completed_at=_now(),
                    )
                    .returning(jobs)
                )
            ).mappings().first()
            if row is None:
                row = (
                    await connection.execute(select(jobs).where(jobs.c.id == job_id))
                ).mappings().first()
            if row is None:
                raise KeyError(job_id)
            return _job(row)

    async def get_job(
        self,
        user_id: str,
        job_id: str,
    ) -> JobRecord | None:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(
                    select(jobs).where(
                        jobs.c.id == job_id,
                        jobs.c.user_id == user_id,
                    )
                )
            ).mappings().first()
            if row is None:
                return None
            return await _job_with_artifacts(connection, _job(row))

    async def get_artifact(
        self,
        user_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        async with self.database.transaction() as connection:
            row = (
                await connection.execute(
                    select(artifacts).where(
                        artifacts.c.id == artifact_id,
                        artifacts.c.user_id == user_id,
                    )
                )
            ).mappings().first()
            return _optional_artifact(row)


async def _require_session(
    connection: AsyncConnection,
    user_id: str,
    session_id: str,
    *,
    for_update: bool = False,
) -> SessionRecord:
    statement = select(sessions).where(
        sessions.c.id == session_id,
        sessions.c.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await connection.execute(statement)).mappings().first()
    if row is None:
        raise SessionNotFoundError(session_id)
    return _session(row)


async def _job_with_artifacts(
    connection: AsyncConnection,
    job: JobRecord,
) -> JobRecord:
    rows = (
        await connection.execute(
            select(artifacts)
            .where(artifacts.c.job_id == job.id)
            .order_by(artifacts.c.created_at, artifacts.c.id)
        )
    ).mappings().all()
    return job.model_copy(update={"artifacts": [_artifact(row) for row in rows]})


def _user(row: Mapping[str, Any]) -> UserRecord:
    return UserRecord(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        is_active=bool(row["is_active"]),
    )


def _optional_user(row: Mapping[str, Any] | None) -> UserRecord | None:
    return _user(row) if row is not None else None


def _session(row: Mapping[str, Any]) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _optional_session(row: Mapping[str, Any] | None) -> SessionRecord | None:
    return _session(row) if row is not None else None


def _message(row: Mapping[str, Any]) -> MessageRecord:
    metadata = row["metadata_json"]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return MessageRecord(
        id=row["id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        role=row["role"],
        content=row["content"],
        metadata=metadata,
        created_at=row["created_at"],
    )


def _job(row: Mapping[str, Any]) -> JobRecord:
    return JobRecord(
        id=row["id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        user_message_id=row["user_message_id"],
        status=JobStatus(row["status"]),
        question=row["question"],
        result_text=row["result_text"],
        assistant_message_id=row["assistant_message_id"],
        error=row["error"],
        error_type=row["error_type"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _artifact(row: Mapping[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        id=row["id"],
        source_artifact_id=row["source_artifact_id"],
        job_id=row["job_id"],
        message_id=row["message_id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        title=row["title"],
        mime_type=row["mime_type"],
        storage_key=row["storage_key"],
        width=row["width"],
        height=row["height"],
        chart_type=row["chart_type"],
        created_at=row["created_at"],
    )


def _optional_artifact(
    row: Mapping[str, Any] | None,
) -> ArtifactRecord | None:
    return _artifact(row) if row is not None else None


def _now() -> datetime:
    return datetime.now(UTC)


def _session_title(question: str) -> str:
    compact = " ".join(question.split()).strip()
    return compact[:18] or "新对话"


def _encode_cursor(timestamp: datetime, item_id: str) -> str:
    payload = json.dumps(
        {"timestamp": timestamp.isoformat(), "id": item_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        timestamp = datetime.fromisoformat(payload["timestamp"])
        item_id = payload["id"]
        if not isinstance(item_id, str):
            raise ValueError
        return timestamp, item_id
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
