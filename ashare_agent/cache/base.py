from typing import Any, Protocol


class CacheStore(Protocol):
    async def get(
        self,
        key: str,
    ) -> Any | None: ...

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: float,
    ) -> None: ...

    async def delete(
        self,
        key: str,
    ) -> None: ...
