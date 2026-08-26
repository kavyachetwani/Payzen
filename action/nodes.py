"""LangGraph node functions for the recovery action pipeline."""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from datetime import datetime

from diagnosis.rules import diagnose
from diagnosis.db import get_connection, create_schema, load_data
from decision.policy import is_retryable, route_action, max_attempts
from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS, ARMS
from decision.stopping import check_stop
from decision.constraints import ConstraintTracker

DATA_DIR = Path(__file__).parent.parent / "data"
BANDIT_CONFIG = Path(__file__).parent.parent / "decision" / "bandit_config.json"
RETRY_DATA = DATA_DIR / "retry_outcomes.json"

_db_conn = None
_bandit = None
_constraint_tracker = None
_success_rates = None
_rng = None


def _get_db():
    global _db_conn
    if _db_conn is None:
        db_path = Path(__file__).parent / "pipeline.db"
        _db_conn = get_connection(db_path)
        create_schema(_db_conn)
        load_data(_db_conn, DATA_DIR / "failed_payments.json")
    return _db_conn


def _get_bandit():
    global _bandit
    if _bandit is None:
        config = json.loads(BANDIT_CONFIG.read_text())
        _bandit = ContextualBandit(
            epsilon=config["epsilon"],
            learning_rate=config["learning_rate"],
            seed=config["seed"],
        )
        train_data = json.loads(RETRY_DATA.read_text())
        for _ in range(config.get("n_epochs", 1)):
            shuffled = list(train_data)
            np.random.RandomState(config["seed"]).shuffle(shuffled)
            _bandit.train_on_dataset(shuffled)
    return _bandit


def _get_constraint_tracker():
    global _constraint_tracker
    if _constraint_tracker is None:
        _constraint_tracker = ConstraintTracker()
    return _constraint_tracker


def _get_success_rates():
    global _success_rates
    if _success_rates is None:
        data = json.loads(RETRY_DATA.read_text())
        rates = defaultdict(lambda: {"success": 0, "total": 0})
        for r in data:
            key = (r["original_cause"], r["action_type"])
            rates[key]["total"] += 1
            if r["outcome"] == "success":
                rates[key]["success"] += 1
        _success_rates = {
            k: v["success"] / v["total"]
            for k, v in rates.items() if v["total"] >= 3
        }
    return _success_rates


def _get_rng():
    global _rng
    if _rng is None:
        _rng = np.random.RandomState(42)
    return _rng


def reset_globals():
    global _db_conn, _bandit, _constraint_tracker, _success_rates, _rng
    if _db_conn:
        _db_conn.close()
    _db_conn = None
    _bandit = None
    _constraint_tracker = None
    _success_rates = None
    _rng = None


def diagnosis_node(state: dict) -> dict:
    conn = _get_db()
    result = diagnose(state["payment_id"], conn)
    return {
        "diagnosis": {
            "cause": result["diagnosed_cause"],
            "confidence": result["confidence"],
        }
    }


def decision_node(state: dict) -> dict:
    cause = state["diagnosis"]["cause"]
    confidence = state["diagnosis"]["confidence"]
    retryable = is_retryable(cause)
    route = route_action(cause)

    if not retryable:
        return {
            "decision": {
                "action_type": None,
                "is_retryable": False,
                "route_to": route,
                "attempt_number": 0,
            },
            "constraint_result": {
                "original_action": None,
                "actual_action": None,
                "downgrade_reason": None,
            },
        }

    record = state.get("payment_record", {})
    bandit_context = {
        "original_cause": cause,
        "time_of_day": 10,
        "day_of_week": 2,
        "days_since_failure": 1,
        "days_since_estimated_payday": 0,
        "amount": state["amount"],
        "retry_attempt_number": 1,
        "pre_debit_notification_sent": record.get("pre_debit_notification_sent", True),
    }

    bandit = _get_bandit()
    action = bandit.select_action(bandit_context)

    stop = check_stop(
        cause=cause, attempt_number=1,
        last_retry_time=None, current_time=None,
        pre_debit_notification_sent=record.get("pre_debit_notification_sent", True),
        payment_method=state.get("payment_method", "enach"),
    )

    if stop.get("force_action"):
        action = stop["force_action"]

    tracker = _get_constraint_tracker()
    sim_time = datetime(2026, 1, 15, 10, 0, 0)
    constraint = tracker.apply_constraints(
        action, state["customer_id"], sim_time, state["payment_id"]
    )

    final_action = constraint["action"]

    decision = {
        "action_type": final_action,
        "is_retryable": True,
        "route_to": None,
        "attempt_number": 1,
    }

    constraint_result = {
        "original_action": constraint["original_action"],
        "actual_action": constraint["action"],
        "downgrade_reason": constraint.get("reason"),
    }

    if confidence < 0.5 and cause != "ambiguous":
        decision["route_to"] = "escalation"
        decision["is_retryable"] = False

    return {"decision": decision, "constraint_result": constraint_result}


def auto_retry_node(state: dict) -> dict:
    cause = state["diagnosis"]["cause"]
    action = state["decision"]["action_type"]
    amount = state["amount"]

    rates = _get_success_rates()
    prob = rates.get((cause, action), 0.1)
    rng = _get_rng()
    success = rng.random() < prob
    cost = ACTION_COSTS[action]

    details = f"retry via {action}"
    if action == "sms_then_retry":
        details = f"SMS sent to customer, then retry attempted"
    elif action == "call_then_retry":
        details = f"call made to customer, then retry attempted"

    outcome = {
        "success": success,
        "amount_recovered": amount if success else 0.0,
        "action_cost": cost,
        "details": f"{details} — {'success' if success else 'failure'}",
    }

    audit = {
        "payment_id": state["payment_id"],
        "customer_id": state["customer_id"],
        "cause": cause,
        "action_type": action,
        "action_node": "auto_retry",
        "success": success,
        "amount_recovered": outcome["amount_recovered"],
        "action_cost": cost,
    }

    return {"action_outcome": outcome, "audit_entry": audit}


def card_update_link_node(state: dict) -> dict:
    outcome = {
        "success": True,
        "amount_recovered": 0.0,
        "action_cost": 2.0,
        "details": "card update link sent via SMS",
    }
    audit = {
        "payment_id": state["payment_id"],
        "customer_id": state["customer_id"],
        "cause": state["diagnosis"]["cause"],
        "action_type": "card_update_link",
        "action_node": "card_update_link",
        "success": True,
        "amount_recovered": 0.0,
        "action_cost": 2.0,
    }
    return {"action_outcome": outcome, "audit_entry": audit}


def mandate_resequence_node(state: dict) -> dict:
    outcome = {
        "success": True,
        "amount_recovered": 0.0,
        "action_cost": 0.0,
        "details": "mandate re-registration initiated",
    }
    audit = {
        "payment_id": state["payment_id"],
        "customer_id": state["customer_id"],
        "cause": state["diagnosis"]["cause"],
        "action_type": "mandate_resequence",
        "action_node": "mandate_resequence",
        "success": True,
        "amount_recovered": 0.0,
        "action_cost": 0.0,
    }
    return {"action_outcome": outcome, "audit_entry": audit}


def escalation_node(state: dict) -> dict:
    cause = state["diagnosis"]["cause"]
    confidence = state["diagnosis"]["confidence"]

    if cause == "mandate_revoked":
        reason = "customer deliberately cancelled mandate — recovery requires conversation, not retry"
    elif confidence < 0.5:
        reason = f"low confidence diagnosis ({confidence:.2f}) — needs human review"
    else:
        reason = f"escalated for cause: {cause}"

    outcome = {
        "success": False,
        "amount_recovered": 0.0,
        "action_cost": 0.0,
        "details": f"escalated to human review — reason: {reason}",
    }
    audit = {
        "payment_id": state["payment_id"],
        "customer_id": state["customer_id"],
        "cause": cause,
        "action_type": "escalation",
        "action_node": "escalation",
        "success": False,
        "amount_recovered": 0.0,
        "action_cost": 0.0,
        "escalation_reason": reason,
    }
    return {"action_outcome": outcome, "audit_entry": audit}
