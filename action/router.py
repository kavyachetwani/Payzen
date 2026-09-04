"""Conditional edge router for the LangGraph recovery pipeline."""


def route_to_action(state: dict) -> str:
    decision = state.get("decision", {})
    diagnosis = state.get("diagnosis", {})

    if diagnosis.get("confidence", 1.0) < 0.5 and decision.get("route_to") == "escalation":
        return "escalation"

    if decision.get("is_retryable"):
        return "auto_retry"

    route = decision.get("route_to")
    if route == "card_update_link":
        return "card_update_link"
    elif route == "mandate_resequence":
        return "mandate_resequence"
    elif route in ("escalation", "escalation_conversation", "customer_auth_action"):
        return "escalation"

    return "escalation"
