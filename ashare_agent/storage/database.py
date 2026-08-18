import asyncio
from collections.abc import Callable
from pathlib import Path
import sqlite3
from typing import TypeVar

T = TypeVar("T")


class AppDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def run(
        self,
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        await self.initialize()
        return await asyncio.to_thread(self._run_sync, operation)

    async def initialize(self) -> None:
        if self._initialized:
            return

        async with self._initialize_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _run_sync(
        self,
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        with self._connect() as connection:
            return operation(connection)

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    question TEXT NOT NULL,
                    result_text TEXT,
                    assistant_message_id TEXT,
                    error TEXT,
                    error_type TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (user_message_id) REFERENCES messages(id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    source_artifact_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    chart_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (message_id) REFERENCES messages(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_updated
                    ON sessions(user_id, updated_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                    ON messages(session_id, user_id, created_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_user_created
                    ON jobs(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_session_status
                    ON jobs(session_id, status);
                CREATE INDEX IF NOT EXISTS idx_artifacts_job
                    ON artifacts(job_id);
                """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
