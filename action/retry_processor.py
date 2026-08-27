"""Retry event processor for the SimClock driver loop.

Handles a single retry event popped from the queue:
1. Execute the retry (simulate success/failure based on timing context)
2. If failed and retriable: schedule next attempt via bandit + constraints
3. If failed and exhausted: create escalation record
4. If succeeded: create recovery record
"""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import numpy as np

from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS
from decision.policy import max_attempts
from decision.stopping import check_stop
from decision.constraints import ConstraintTracker
from action.compliance import is_dnd

DATA_DIR = Path(__file__).parent.parent / "data"
RETRY_DATA = DATA_DIR / "retry_outcomes.json"
BANDIT_CONFIG = Path(__file__).parent.parent / "decision" / "bandit_config.json"

ATTEMPT_DECAY = {1: 1.0, 2: 0.8, 3: 0.6}

_success_rates = None


def _load_success_rates():
    global _success_rates
    if _success_rates is not None:
        return _success_rates
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


def reset_success_rates():
    global _success_rates
    _success_rates = None


def _days_since_payday(dt: datetime) -> int:
    if dt.day >= 1:
        return dt.day - 1
    return 0


def simulate_retry_outcome(cause: str, action: str, attempt_number: int,
                           retry_time: datetime, rng: np.random.RandomState) -> bool:
    rates = _load_success_rates()
    base_rate = rates.get((cause, action), 0.10)
    decay = ATTEMPT_DECAY.get(attempt_number, 0.5)
    effective_rate = base_rate * decay

    payday_dist = _days_since_payday(retry_time)
    if cause == "insufficient_funds" and payday_dist <= 3:
        effective_rate = min(effective_rate * 1.25, 0.95)

    return rng.random() < effective_rate


def process_retry_event(event: dict, payment_records: dict,
                        bandit: ContextualBandit,
                        constraint_tracker: ConstraintTracker,
                        event_queue, clock,
                        rng: np.random.RandomState,
                        history: dict) -> dict:
    """Process a single retry event from the queue.

    Returns a result dict with outcome details.
    """
    payload = event["payload"]
    payment_id = payload["payment_id"]
    cause = payload["cause"]
    action = payload["action_type"]
    attempt_number = payload["attempt_number"]
    payment_method = payload["payment_method"]
    cost = ACTION_COSTS.get(action, 0.0)

    record = payment_records[payment_id]
    amount = record["amount"]
    customer_id = record["customer_id"]
    retry_time = clock.now()

    success = simulate_retry_outcome(cause, action, attempt_number, retry_time, rng)

    attempt_entry = {
        "attempt": attempt_number,
        "time": retry_time.isoformat(),
        "action": action,
        "cause": cause,
        "outcome": "success" if success else "failure",
        "cost": cost,
        "recovered": amount if success else 0.0,
    }

    if payment_id not in history:
        history[payment_id] = []
    history[payment_id].append(attempt_entry)

    if success:
        return {
            "payment_id": payment_id,
            "status": "recovered",
            "attempt_number": attempt_number,
            "amount_recovered": amount,
            "action_cost": cost,
            "retry_time": retry_time,
        }

    cap = max_attempts(cause)
    if attempt_number >= cap:
        return {
            "payment_id": payment_id,
            "status": "escalated",
            "attempt_number": attempt_number,
            "amount_recovered": 0.0,
            "action_cost": cost,
            "retry_time": retry_time,
            "reason": f"exhausted {cap} attempts for {cause}",
        }

    next_attempt = attempt_number + 1
    failure_time_str = record["failure_timestamp"]
    failure_time = datetime.fromisoformat(failure_time_str)

    payday_dist = _days_since_payday(retry_time)
    days_since_failure = (retry_time - failure_time).total_seconds() / 86400

    bandit_context = {
        "original_cause": cause,
        "time_of_day": retry_time.hour,
        "day_of_week": retry_time.weekday(),
        "days_since_failure": days_since_failure,
        "days_since_estimated_payday": payday_dist,
        "amount": amount,
        "retry_attempt_number": next_attempt,
        "pre_debit_notification_sent": record.get("pre_debit_notification_sent", True),
    }

    next_action = bandit.select_action(bandit_context)

    stop = check_stop(
        cause=cause, attempt_number=next_attempt,
        last_retry_time=retry_time.isoformat(),
        current_time=(retry_time + __import__('datetime').timedelta(hours=24)).isoformat(),
        pre_debit_notification_sent=record.get("pre_debit_notification_sent", True),
        payment_method=payment_method,
    )

    if stop.get("force_action"):
        next_action = stop["force_action"]

    if is_dnd(customer_id) and next_action in ("sms_then_retry", "call_then_retry"):
        next_action = "auto_retry"

    from decision.scheduler import schedule_retry as _schedule
    from decision.stopping import UPI_ATTEMPT_MIN_HOURS

    delay_hours = 24.0
    if payment_method == "upi_autopay":
        delay_hours = max(delay_hours, UPI_ATTEMPT_MIN_HOURS.get(next_attempt, 24))

    scheduled_time = retry_time + __import__('datetime').timedelta(hours=delay_hours)

    if payment_method == "upi_autopay":
        from decision.scheduler import _enforce_upi_spacing, _clamp_upi_time
        from decision.constraints import clamp_upi_call
        scheduled_time = _enforce_upi_spacing(scheduled_time, failure_time, next_attempt)
        if next_action == "call_then_retry":
            scheduled_time = clamp_upi_call(scheduled_time)
        else:
            scheduled_time = _clamp_upi_time(scheduled_time)
    else:
        if next_action == "call_then_retry":
            from decision.constraints import clamp_call_to_rbi_hours
            scheduled_time = clamp_call_to_rbi_hours(scheduled_time)

    constraint = constraint_tracker.apply_constraints(
        next_action, customer_id, scheduled_time, payment_id
    )
    final_action = constraint["action"]

    next_cost = ACTION_COSTS.get(final_action, 0.0)

    event_queue.enqueue(
        event_type="retry_attempt",
        scheduled_time=scheduled_time,
        payload={
            "payment_id": payment_id,
            "cause": cause,
            "action_type": final_action,
            "attempt_number": next_attempt,
            "action_cost": next_cost,
            "payment_method": payment_method,
        },
    )

    return {
        "payment_id": payment_id,
        "status": "scheduled_next",
        "attempt_number": attempt_number,
        "amount_recovered": 0.0,
        "action_cost": cost,
        "retry_time": retry_time,
        "next_attempt": next_attempt,
        "next_action": final_action,
        "next_time": scheduled_time,
    }
