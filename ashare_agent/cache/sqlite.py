import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any


class SqliteCacheStore:
    def __init__(
        self,
        database_path: str | Path,
    ):
        self._database_path = Path(database_path).expanduser()
        self._initialized = False
        self._initialize_lock = asyncio.Lock()
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    async def get(
        self,
        key: str,
    ) -> Any | None:
        await self._ensure_initialized()
        return await asyncio.to_thread(self._get_sync, key)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: float,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Cache TTL must be greater than zero")

        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        now = time.time()
        expires_at = now + ttl_seconds

        await self._ensure_initialized()
        await asyncio.to_thread(
            self._set_sync,
            key,
            payload,
            expires_at,
            now,
        )

    async def delete(
        self,
        key: str,
    ) -> None:
        await self._ensure_initialized()
        await asyncio.to_thread(self._delete_sync, key)

    @asynccontextmanager
    async def lock(self, key: str):
        refresh_lock = self._refresh_locks.setdefault(key, asyncio.Lock())
        async with refresh_lock:
            yield

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        async with self._initialize_lock:
            if self._initialized:
                return

            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _initialize_sync(self) -> None:
        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """)

    def _get_sync(
        self,
        key: str,
    ) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT value_json, expires_at
                FROM cache_entries
                WHERE cache_key = ?
                """,
                (key,),
            ).fetchone()

            if row is None:
                return None

            payload, expires_at = row

            if expires_at <= time.time():
                connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?",
                    (key,),
                )
                return None

            try:
                return json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                connection.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?",
                    (key,),
                )
                return None

    def _set_sync(
        self,
        key: str,
        payload: str,
        expires_at: float,
        updated_at: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cache_entries (
                    cache_key,
                    value_json,
                    expires_at,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    payload,
                    expires_at,
                    updated_at,
                ),
            )

    def _delete_sync(
        self,
        key: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM cache_entries WHERE cache_key = ?",
                (key,),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=5.0,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
