from collections.abc import Mapping
from typing import Any

from langgraph.graph import (
    StateGraph,
    START,
    END,
)

from .state import AgentState

from .nodes import (
    create_default_nodes,
)

from .routing import (
    route_after_understand,
    route_after_plan,
    route_after_analyze,
    route_after_reflect,
)

REQUIRED_NODES = {
    "understand",
    "plan",
    "execute",
    "analyze",
    "reflect",
    "answer",
}


def build_graph(
    nodes: Mapping[str, Any],
):
    missing = REQUIRED_NODES - set(nodes.keys())

    if missing:
        raise ValueError(f"Missing nodes: {sorted(missing)}")

    graph = StateGraph(AgentState)

    # =========================
    # Nodes
    # =========================

    graph.add_node(
        "understand",
        nodes["understand"],
    )

    graph.add_node(
        "plan",
        nodes["plan"],
    )

    graph.add_node(
        "execute",
        nodes["execute"],
    )

    graph.add_node(
        "analyze",
        nodes["analyze"],
    )

    graph.add_node(
        "reflect",
        nodes["reflect"],
    )

    graph.add_node(
        "answer",
        nodes["answer"],
    )

    # =========================
    # Edges
    # =========================

    graph.add_edge(
        START,
        "understand",
    )

    graph.add_conditional_edges(
        "understand",
        route_after_understand,
        {
            "plan": "plan",
            "answer": "answer",
        },
    )

    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {
            "execute": "execute",
            "answer": "answer",
        },
    )

    graph.add_edge(
        "execute",
        "analyze",
    )

    graph.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "plan": "plan",
            "reflect": "reflect",
            "answer": "answer",
        },
    )

    graph.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {
            "plan": "plan",
            "answer": "answer",
        },
    )

    graph.add_edge(
        "answer",
        END,
    )

    return graph.compile()


def create_default_graph():
    nodes = create_default_nodes()

    return build_graph(nodes)
