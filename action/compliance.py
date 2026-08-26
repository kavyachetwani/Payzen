"""Compliance checks for the recovery pipeline.

Four checks, run in order:
1. DND opt-out — block SMS/call to customers who opted out
2. Pre-debit notification — force SMS on first retry if notification wasn't sent
3. Contact hours safety net — RBI 8AM-7PM (should catch 0 if Stage 4.1 works)
4. Contact limits safety net — per-customer caps (should catch 0 if Stage 4.2 works)
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent.parent / "data"

_dnd_set = None


def _load_dnd_set():
    global _dnd_set
    if _dnd_set is not None:
        return _dnd_set

    records = json.loads((DATA_DIR / "failed_payments.json").read_text())
    customers = sorted(set(r["customer_id"] for r in records))
    rng = np.random.RandomState(99)
    n_dnd = max(1, int(len(customers) * 0.05))
    dnd_indices = rng.choice(len(customers), size=n_dnd, replace=False)
    _dnd_set = {customers[i] for i in dnd_indices}
    return _dnd_set


def reset_dnd():
    global _dnd_set
    _dnd_set = None


def is_dnd(customer_id: str) -> bool:
    return customer_id in _load_dnd_set()


def get_dnd_set():
    return _load_dnd_set()


def _action_contacts_customer(action: str) -> bool:
    return action in ("sms_then_retry", "call_then_retry", "card_update_link")


def check_dnd(customer_id: str, action: str, cause: str, is_retryable: bool):
    if not _action_contacts_customer(action):
        return {"passed": True}

    if not is_dnd(customer_id):
        return {"passed": True}

    if is_retryable:
        return {
            "passed": False,
            "reason": "DND opt-out",
            "remedy": "downgrade_to_auto_retry",
            "details": f"customer {customer_id} is DND — downgrading to auto_retry",
        }
    else:
        return {
            "passed": False,
            "reason": "DND opt-out",
            "remedy": "block",
            "details": f"customer {customer_id} is DND — no contactless action available",
        }


def check_pre_debit_notification(payment_record: dict, action: str, attempt_number: int):
    if attempt_number != 1:
        return {"passed": True}

    if payment_record.get("pre_debit_notification_sent", True):
        return {"passed": True}

    if action == "sms_then_retry":
        return {"passed": True}

    return {
        "passed": False,
        "reason": "pre-debit notification not sent",
        "remedy": "force_sms_then_retry",
        "details": "first retry without pre-debit notification — forcing sms_then_retry",
    }


def check_contact_hours(action: str, current_time: datetime):
    if not _action_contacts_customer(action):
        return {"passed": True}

    hour = current_time.hour
    if 8 <= hour < 19:
        return {"passed": True}

    return {
        "passed": False,
        "reason": "outside RBI contact hours (8AM-7PM)",
        "remedy": "block",
        "details": f"contact action at {current_time.strftime('%H:%M')} violates RBI hours",
    }


def check_contact_limits(customer_id: str, action: str, constraint_tracker):
    if not _action_contacts_customer(action):
        return {"passed": True}

    if constraint_tracker is None:
        return {"passed": True}

    calls = len(constraint_tracker.customer_calls.get(customer_id, []))
    sms = len(constraint_tracker.customer_sms.get(customer_id, []))

    if action == "call_then_retry" and calls > 1:
        return {
            "passed": False,
            "reason": "call limit exceeded",
            "remedy": "block",
            "details": f"customer {customer_id} already has {calls} calls in cycle",
        }

    if action in ("sms_then_retry", "card_update_link") and sms > 3:
        return {
            "passed": False,
            "reason": "SMS limit exceeded",
            "remedy": "block",
            "details": f"customer {customer_id} already has {sms} SMS in cycle",
        }

    return {"passed": True}


def _effective_action(decision: dict) -> str | None:
    action = decision.get("action_type")
    if action is not None:
        return action
    route = decision.get("route_to")
    if route in ("card_update_link", "mandate_resequence", "escalation", "escalation_conversation"):
        return route
    return None


def run_compliance_checks(state: dict, constraint_tracker=None):
    decision = state.get("decision", {})
    action = _effective_action(decision)
    cause = state.get("diagnosis", {}).get("cause", "unknown")
    is_retryable = decision.get("is_retryable", False)
    customer_id = state["customer_id"]
    record = state.get("payment_record", {})
    attempt = decision.get("attempt_number", 1)

    if action is None:
        return {"all_passed": True, "checks": [], "final_action": action}

    sim_time = datetime(2026, 1, 15, 10, 0, 0)

    checks = [
        ("dnd", check_dnd(customer_id, action, cause, is_retryable)),
        ("pre_debit", check_pre_debit_notification(record, action, attempt)),
        ("contact_hours", check_contact_hours(action, sim_time)),
        ("contact_limits", check_contact_limits(customer_id, action, constraint_tracker)),
    ]

    final_action = action
    violations = []

    for name, result in checks:
        if result["passed"]:
            continue

        violations.append({"check": name, **result})
        remedy = result.get("remedy")

        if remedy == "downgrade_to_auto_retry":
            final_action = "auto_retry"
        elif remedy == "force_sms_then_retry":
            final_action = "sms_then_retry"
        elif remedy == "block":
            final_action = None
            break

    return {
        "all_passed": len(violations) == 0,
        "checks": violations,
        "final_action": final_action,
        "original_action": action,
    }
