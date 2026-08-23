import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)

from .schema import metadata


class AppDatabase:
    def __init__(
        self,
        url: str,
        *,
        create_schema: bool = False,
    ) -> None:
        self.url = url
        self._create_schema = create_schema
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
        )
        self._initialized = False
        self._initialize_lock = asyncio.Lock()
        if url.startswith("sqlite+"):
            _enable_sqlite_foreign_keys(self._engine)

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            async with self._engine.begin() as connection:
                if self._create_schema:
                    await connection.run_sync(metadata.create_all)
                else:
                    await connection.execute(text("SELECT 1"))
            self._initialized = True

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        await self.initialize()
        async with self._engine.begin() as connection:
            yield connection

    async def close(self) -> None:
        await self._engine.dispose()
        self._initialized = False


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
