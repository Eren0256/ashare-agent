from typing import Any

from .models import ToolSpec
from .registry import ToolRegistry


class ToolSelector:
    def __init__(
        self,
        registry: ToolRegistry,
    ):
        self._registry = registry

    async def aselect(
        self,
        query: str,
        task: Any = None,
        top_k: int = 8,
    ) -> list[ToolSpec]:

        query_lower = query.lower()

        intent = getattr(
            task,
            "intent",
            None,
        )

        scored: list[tuple[int, ToolSpec]] = []

        for spec in self._registry.specs():
            score = 0

            # -------------------------
            # intent 匹配
            # -------------------------

            if intent and intent in spec.intents:
                score += 100

            # -------------------------
            # keyword 匹配
            # -------------------------

            for keyword in spec.keywords:
                if keyword.lower() in query_lower:
                    score += 10

            if score > 0:
                scored.append(
                    (
                        score,
                        spec,
                    )
                )

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [spec for _, spec in scored[:top_k]]
