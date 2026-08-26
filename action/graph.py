"""LangGraph graph assembly for the recovery action pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, END

from action.state import PipelineState
from action.nodes import (
    diagnosis_node, decision_node, auto_retry_node,
    card_update_link_node, mandate_resequence_node, escalation_node,
)
from action.router import route_to_action


def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("diagnose", diagnosis_node)
    graph.add_node("decide", decision_node)
    graph.add_node("retry", auto_retry_node)
    graph.add_node("card_update", card_update_link_node)
    graph.add_node("resequence", mandate_resequence_node)
    graph.add_node("escalate", escalation_node)

    graph.set_entry_point("diagnose")
    graph.add_edge("diagnose", "decide")

    graph.add_conditional_edges(
        "decide",
        route_to_action,
        {
            "auto_retry": "retry",
            "card_update_link": "card_update",
            "mandate_resequence": "resequence",
            "escalation": "escalate",
        },
    )

    graph.add_edge("retry", END)
    graph.add_edge("card_update", END)
    graph.add_edge("resequence", END)
    graph.add_edge("escalate", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()
    print("Graph compiled successfully.")
    print(f"Nodes: {list(app.get_graph().nodes)}")
