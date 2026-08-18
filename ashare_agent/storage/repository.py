import base64
from datetime import UTC, datetime
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ashare_agent.domain import ChartArtifact

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


class SessionNotFoundError(LookupError):
    pass


class SessionBusyError(RuntimeError):
    pass


class ApplicationRepository:
    def __init__(self, database: AppDatabase):
        self.database = database

    async def create_user(
        self,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> UserRecord:
        def operation(connection: sqlite3.Connection) -> UserRecord:
            existing = connection.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if existing is not None:
                return _user(existing)

            user = UserRecord(
                id=uuid4().hex,
                username=username,
                display_name=display_name,
                password_hash=password_hash,
            )
            connection.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash,
                    is_active, created_at
                ) VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.display_name,
                    user.password_hash,
                    _now(),
                ),
            )
            return user

        return await self.database.run(operation)

    async def get_user_by_username(
        self,
        username: str,
    ) -> UserRecord | None:
        return await self.database.run(
            lambda connection: _optional_user(
                connection.execute(
                    "SELECT * FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
            )
        )

    async def get_user_by_id(
        self,
        user_id: str,
    ) -> UserRecord | None:
        return await self.database.run(
            lambda connection: _optional_user(
                connection.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            )
        )

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

        def operation(connection: sqlite3.Connection) -> SessionRecord:
            connection.execute(
                """
                INSERT INTO sessions (
                    id, user_id, title, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.user_id,
                    session.title,
                    session.created_at,
                    session.updated_at,
                ),
            )
            return session

        return await self.database.run(operation)

    async def get_session(
        self,
        user_id: str,
        session_id: str,
    ) -> SessionRecord | None:
        return await self.database.run(
            lambda connection: _optional_session(
                connection.execute(
                    "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
                    (session_id, user_id),
                ).fetchone()
            )
        )

    async def delete_session(
        self,
        user_id: str,
        session_id: str,
    ) -> bool:
        def operation(connection: sqlite3.Connection) -> bool:
            active_job = connection.execute(
                """
                SELECT id FROM jobs
                WHERE session_id = ? AND user_id = ?
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (session_id, user_id),
            ).fetchone()
            if active_job is not None:
                raise SessionBusyError(session_id)
            cursor = connection.execute(
                "DELETE FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
            return cursor.rowcount > 0

        return await self.database.run(operation)

    async def list_sessions(
        self,
        user_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 50))

        def operation(connection: sqlite3.Connection) -> dict[str, Any]:
            params: list[Any] = [user_id]
            cursor_sql = ""
            if cursor:
                updated_at, session_id = _decode_cursor(cursor)
                cursor_sql = "AND (updated_at < ? OR " "(updated_at = ? AND id < ?))"
                params.extend([updated_at, updated_at, session_id])
            params.append(limit + 1)
            rows = connection.execute(
                f"""
                SELECT * FROM sessions
                WHERE user_id = ? {cursor_sql}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            items = [_session(row) for row in rows[:limit]]
            next_cursor = None
            if len(rows) > limit and items:
                last = items[-1]
                next_cursor = _encode_cursor(last.updated_at, last.id)
            return {"items": items, "next_cursor": next_cursor}

        return await self.database.run(operation)

    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 50))

        def operation(connection: sqlite3.Connection) -> dict[str, Any]:
            _require_session(connection, user_id, session_id)
            params: list[Any] = [session_id, user_id]
            cursor_sql = ""
            if cursor:
                created_at, message_id = _decode_cursor(cursor)
                cursor_sql = "AND (created_at < ? OR " "(created_at = ? AND id < ?))"
                params.extend([created_at, created_at, message_id])
            params.append(limit + 1)
            rows = connection.execute(
                f"""
                SELECT * FROM messages
                WHERE session_id = ? AND user_id = ? {cursor_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            newest = [_message(row) for row in rows[:limit]]
            next_cursor = None
            if len(rows) > limit and newest:
                last = newest[-1]
                next_cursor = _encode_cursor(last.created_at, last.id)
            return {
                "items": list(reversed(newest)),
                "next_cursor": next_cursor,
            }

        return await self.database.run(operation)

    async def submit_turn(
        self,
        user_id: str,
        session_id: str,
        question: str,
        *,
        context_limit: int,
    ) -> SubmittedTurn:
        question = question.strip()
        if not question:
            raise ValueError("question cannot be empty")

        def operation(connection: sqlite3.Connection) -> SubmittedTurn:
            session = _require_session(connection, user_id, session_id)
            active_job = connection.execute(
                """
                SELECT id FROM jobs
                WHERE session_id = ? AND user_id = ?
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (session_id, user_id),
            ).fetchone()
            if active_job is not None:
                raise SessionBusyError(session_id)

            context_rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (session_id, user_id, max(0, context_limit)),
            ).fetchall()
            context = [
                {"role": item.role, "content": item.content}
                for item in reversed([_message(row) for row in context_rows])
            ]

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
            connection.execute(
                """
                INSERT INTO messages (
                    id, session_id, user_id, role, content,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, '{}', ?)
                """,
                (
                    message.id,
                    session_id,
                    user_id,
                    message.role,
                    message.content,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, session_id, user_id, user_message_id,
                    status, question, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    session_id,
                    user_id,
                    message.id,
                    job.status.value,
                    question,
                    now,
                ),
            )
            title = session.title
            if title == "新对话":
                title = _session_title(question)
            connection.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (title, now, session_id, user_id),
            )
            return SubmittedTurn(
                job=job,
                user_message=message,
                context=context,
            )

        return await self.database.run(operation)

    async def mark_job_running(self, job_id: str) -> JobRecord:
        def operation(connection: sqlite3.Connection) -> JobRecord:
            connection.execute(
                """
                UPDATE jobs SET status = 'running', started_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (_now(), job_id),
            )
            return _require_job(connection, job_id)

        return await self.database.run(operation)

    async def complete_job(
        self,
        job_id: str,
        text: str,
        artifacts: list[ChartArtifact],
    ) -> JobRecord:
        def operation(connection: sqlite3.Connection) -> JobRecord:
            job = _require_job(connection, job_id)
            if job.status == JobStatus.SUCCEEDED:
                return _job_with_artifacts(connection, job)
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
                    file_path=str(artifact.file_path.resolve()),
                    width=artifact.width,
                    height=artifact.height,
                    chart_type=artifact.chart_type.value,
                    created_at=now,
                )
                for artifact in artifacts
            ]
            metadata = {
                "job_id": job.id,
                "artifacts": [item.public_dict() for item in records],
            }
            connection.execute(
                """
                INSERT INTO messages (
                    id, session_id, user_id, role, content,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, 'assistant', ?, ?, ?)
                """,
                (
                    message_id,
                    job.session_id,
                    job.user_id,
                    text,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                ),
            )
            for item in records:
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        id, source_artifact_id, job_id, message_id,
                        session_id, user_id, title, mime_type,
                        file_path, width, height, chart_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.source_artifact_id,
                        item.job_id,
                        item.message_id,
                        item.session_id,
                        item.user_id,
                        item.title,
                        item.mime_type,
                        item.file_path,
                        item.width,
                        item.height,
                        item.chart_type,
                        item.created_at,
                    ),
                )
            connection.execute(
                """
                UPDATE jobs SET
                    status = 'succeeded', result_text = ?,
                    assistant_message_id = ?, completed_at = ?
                WHERE id = ?
                """,
                (text, message_id, now, job.id),
            )
            connection.execute(
                """
                UPDATE sessions SET updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, job.session_id, job.user_id),
            )
            return _job_with_artifacts(
                connection,
                _require_job(connection, job.id),
            )

        return await self.database.run(operation)

    async def fail_job(
        self,
        job_id: str,
        error: Exception,
    ) -> JobRecord:
        def operation(connection: sqlite3.Connection) -> JobRecord:
            connection.execute(
                """
                UPDATE jobs SET
                    status = 'failed', error = ?, error_type = ?,
                    completed_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (str(error), type(error).__name__, _now(), job_id),
            )
            return _require_job(connection, job_id)

        return await self.database.run(operation)

    async def get_job(
        self,
        user_id: str,
        job_id: str,
    ) -> JobRecord | None:
        def operation(connection: sqlite3.Connection) -> JobRecord | None:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
            if row is None:
                return None
            return _job_with_artifacts(connection, _job(row))

        return await self.database.run(operation)

    async def get_artifact(
        self,
        user_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        return await self.database.run(
            lambda connection: _optional_artifact(
                connection.execute(
                    "SELECT * FROM artifacts WHERE id = ? AND user_id = ?",
                    (artifact_id, user_id),
                ).fetchone()
            )
        )

    async def fail_unfinished_jobs(self) -> int:
        def operation(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE jobs SET
                    status = 'failed',
                    error = '服务重启，进程内任务已终止。',
                    error_type = 'ServiceRestarted',
                    completed_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (_now(),),
            )
            return cursor.rowcount

        return await self.database.run(operation)


def _require_session(
    connection: sqlite3.Connection,
    user_id: str,
    session_id: str,
) -> SessionRecord:
    row = connection.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    if row is None:
        raise SessionNotFoundError(session_id)
    return _session(row)


def _require_job(
    connection: sqlite3.Connection,
    job_id: str,
) -> JobRecord:
    row = connection.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise KeyError(job_id)
    return _job(row)


def _job_with_artifacts(
    connection: sqlite3.Connection,
    job: JobRecord,
) -> JobRecord:
    rows = connection.execute(
        "SELECT * FROM artifacts WHERE job_id = ? ORDER BY created_at, id",
        (job.id,),
    ).fetchall()
    return job.model_copy(update={"artifacts": [_artifact(row) for row in rows]})


def _user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        is_active=bool(row["is_active"]),
    )


def _optional_user(row: sqlite3.Row | None) -> UserRecord | None:
    return _user(row) if row is not None else None


def _session(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _optional_session(row: sqlite3.Row | None) -> SessionRecord | None:
    return _session(row) if row is not None else None


def _message(row: sqlite3.Row) -> MessageRecord:
    try:
        metadata = json.loads(row["metadata_json"])
    except (TypeError, json.JSONDecodeError):
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


def _job(row: sqlite3.Row) -> JobRecord:
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


def _artifact(row: sqlite3.Row) -> ArtifactRecord:
    return ArtifactRecord(
        id=row["id"],
        source_artifact_id=row["source_artifact_id"],
        job_id=row["job_id"],
        message_id=row["message_id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        title=row["title"],
        mime_type=row["mime_type"],
        file_path=row["file_path"],
        width=row["width"],
        height=row["height"],
        chart_type=row["chart_type"],
        created_at=row["created_at"],
    )


def _optional_artifact(
    row: sqlite3.Row | None,
) -> ArtifactRecord | None:
    return _artifact(row) if row is not None else None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _session_title(question: str) -> str:
    compact = " ".join(question.split()).strip()
    return compact[:18] or "新对话"


def _encode_cursor(timestamp: str, item_id: str) -> str:
    payload = json.dumps(
        {"timestamp": timestamp, "id": item_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        timestamp = payload["timestamp"]
        item_id = payload["id"]
        if not isinstance(timestamp, str) or not isinstance(item_id, str):
            raise ValueError
        return timestamp, item_id
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
