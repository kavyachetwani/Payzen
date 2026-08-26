"""Human-in-the-loop approval gate for the recovery pipeline.

Sits between the decision node and the action router. Three modes:
- auto_approve: low-risk actions proceed without human review
- require_approval: customer-facing actions need approval (auto-approved in batch mode)
- reject: compliance violation blocks the action entirely
"""

from action.compliance import run_compliance_checks


def gate_node(state: dict) -> dict:
    decision = state.get("decision", {})
    action = decision.get("action_type")
    is_retryable = decision.get("is_retryable", False)
    route = decision.get("route_to")

    effective_action = action or route
    contacts_customer = effective_action in (
        "sms_then_retry", "call_then_retry", "card_update_link",
    )

    if effective_action is None or (not is_retryable and not contacts_customer):
        return {
            "gate_result": {
                "mode": "auto_approve",
                "approved": True,
                "original_action": effective_action,
                "final_action": effective_action,
                "compliance_violations": [],
                "reason": "non-retryable route — no customer contact",
            }
        }

    from action.nodes import _get_constraint_tracker
    tracker = _get_constraint_tracker()
    compliance = run_compliance_checks(state, constraint_tracker=tracker)

    if not compliance["all_passed"]:
        final_action = compliance["final_action"]

        if final_action is None:
            return {
                "gate_result": {
                    "mode": "reject",
                    "approved": False,
                    "original_action": compliance["original_action"],
                    "final_action": None,
                    "compliance_violations": compliance["checks"],
                    "reason": compliance["checks"][0]["details"] if compliance["checks"] else "compliance violation",
                },
                "decision": {
                    **decision,
                    "action_type": None,
                    "is_retryable": False,
                    "route_to": "blocked",
                },
                "action_outcome": {
                    "success": False,
                    "amount_recovered": 0.0,
                    "action_cost": 0.0,
                    "details": f"blocked by gate — reason: {compliance['checks'][0]['details']}",
                },
                "audit_entry": {
                    "payment_id": state["payment_id"],
                    "customer_id": state["customer_id"],
                    "cause": state.get("diagnosis", {}).get("cause", "unknown"),
                    "action_type": "blocked",
                    "action_node": "gate_blocked",
                    "success": False,
                    "amount_recovered": 0.0,
                    "action_cost": 0.0,
                    "gate_reason": compliance["checks"][0]["details"],
                },
            }

        updated_decision = {**decision, "action_type": final_action}

        mode = "auto_approve" if final_action == "auto_retry" else "require_approval"

        return {
            "gate_result": {
                "mode": mode,
                "approved": True,
                "original_action": compliance["original_action"],
                "final_action": final_action,
                "compliance_violations": compliance["checks"],
                "reason": compliance["checks"][0]["details"] if compliance["checks"] else "",
            },
            "decision": updated_decision,
        }

    if action in ("sms_then_retry", "call_then_retry", "card_update_link"):
        mode = "require_approval"
    else:
        mode = "auto_approve"

    return {
        "gate_result": {
            "mode": mode,
            "approved": True,
            "original_action": action,
            "final_action": action,
            "compliance_violations": [],
            "reason": "all compliance checks passed",
        }
    }
