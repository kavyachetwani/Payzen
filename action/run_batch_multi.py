"""Multi-attempt batch runner: retries play out across simulated time via SimClock.

Phase 1: Initial processing — non-retryable resolved immediately, retryable scheduled
Phase 2: SimClock driver loop — retry events execute in chronological order

All actions are logged to Firestore (or local JSON fallback).
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from simclock.sim_clock import SimClock
from simclock.test_simclock import FakeFirestoreClient
from simclock.event_queue import EventQueue

from action.graph import build_graph
from action.nodes import reset_globals
from action.compliance import get_dnd_set, reset_dnd
from action.retry_processor import (
    process_retry_event, reset_success_rates,
)
from audit.logger import AuditLogger

from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS
from decision.constraints import ConstraintTracker
from decision.stopping import UPI_ATTEMPT_MIN_HOURS
from decision.policy import max_attempts

DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"
BANDIT_CONFIG = Path(__file__).parent.parent / "decision" / "bandit_config.json"
RETRY_DATA = Path(__file__).parent.parent / "data" / "retry_outcomes.json"


def _init_bandit():
    config = json.loads(BANDIT_CONFIG.read_text())
    bandit = ContextualBandit(
        epsilon=config["epsilon"],
        learning_rate=config["learning_rate"],
        seed=config["seed"],
    )
    train_data = json.loads(RETRY_DATA.read_text())
    for _ in range(config.get("n_epochs", 1)):
        shuffled = list(train_data)
        np.random.RandomState(config["seed"]).shuffle(shuffled)
        bandit.train_on_dataset(shuffled)
    return bandit


def _outcome_label(final_state: dict, is_gate_blocked: bool = False) -> str:
    if is_gate_blocked:
        return "gate_blocked"
    audit = final_state.get("audit_entry", {})
    node = audit.get("action_node", "")
    if node == "card_update_link":
        return "card_update_sent"
    if node == "mandate_resequence":
        return "mandate_resequenced"
    if node == "escalation":
        return "escalated"
    return node or "unknown"


def run():
    records = json.loads(DATA_PATH.read_text())
    record_map = {r["payment_id"]: r for r in records}
    print(f"Loading {len(records)} payment records...")

    reset_globals()
    reset_dnd()
    reset_success_rates()

    logger = AuditLogger()

    app = build_graph()
    bandit = _init_bandit()
    constraint_tracker = ConstraintTracker()
    rng = np.random.RandomState(42)

    clock = SimClock(anchor=datetime(2026, 1, 1))
    db = FakeFirestoreClient()
    event_queue = EventQueue(db=db)

    dnd_set = get_dnd_set()
    n_customers = len(set(r["customer_id"] for r in records))
    print(f"DND customers: {len(dnd_set)} ({len(dnd_set)/n_customers:.1%})")

    # ── Phase 1: Initial processing ──
    print("\n── Phase 1: Initial processing ──")

    non_retryable_results = []
    retryable_scheduled = 0
    gate_blocked_results = []
    history = {}
    diagnosis_cache = {}

    for r in records:
        initial_state = {
            "payment_id": r["payment_id"],
            "customer_id": r["customer_id"],
            "payment_method": r["payment_method"],
            "amount": r["amount"],
            "payment_record": r,
        }

        final_state = app.invoke(initial_state)

        decision = final_state.get("decision", {})
        gate = final_state.get("gate_result", {})
        diag = final_state.get("diagnosis", {})
        audit = final_state.get("audit_entry", {})
        constraint = final_state.get("constraint_result", {})
        outcome = final_state.get("action_outcome", {})

        if not gate.get("approved", True):
            gate_blocked_results.append(final_state)

            logger.log_event({
                "payment_id": r["payment_id"],
                "customer_id": r["customer_id"],
                "event_type": "initial_processing",
                "attempt_number": 1,
                "sim_timestamp": r["failure_timestamp"],
                "action_type": "gate_blocked",
                "bandit_recommended_action": gate.get("original_action"),
                "actual_action": "gate_blocked",
                "downgrade_reason": gate.get("reason"),
                "gate_mode": gate.get("mode", "reject"),
                "gate_approved": False,
                "compliance_notes": [v.get("details", "") for v in gate.get("compliance_violations", [])],
                "outcome_success": False,
                "amount_recovered": 0.0,
                "action_cost": 0.0,
                "outcome_details": outcome.get("details", "gate blocked"),
                "timing_context": None,
            })

            logger.log_summary({
                "payment_id": r["payment_id"],
                "customer_id": r["customer_id"],
                "amount": r["amount"],
                "payment_method": r["payment_method"],
                "payment_category": r["payment_category"],
                "bank_name": r["bank_name"],
                "failure_timestamp": r["failure_timestamp"],
                "failure_reason_code": r["failure_reason_code"],
                "diagnosed_cause": diag.get("cause", "unknown"),
                "diagnosis_confidence": diag.get("confidence", 0),
                "ground_truth_cause": r["ground_truth_cause"],
                "is_retryable": False,
                "total_attempts": 0,
                "final_outcome": "gate_blocked",
                "total_amount_recovered": 0.0,
                "total_action_cost": 0.0,
                "net_recovered": 0.0,
                "resolution_sim_timestamp": r["failure_timestamp"],
                "attempt_history": [{
                    "attempt": 0,
                    "action": "gate_blocked",
                    "outcome": "blocked",
                    "time": r["failure_timestamp"],
                    "cost": 0.0,
                    "details": outcome.get("details", "gate blocked"),
                }],
            })
            continue

        is_retryable = decision.get("is_retryable", False)

        if not is_retryable:
            non_retryable_results.append(final_state)
            action_node = audit.get("action_node", "unknown")
            outcome_label = _outcome_label(final_state)

            logger.log_event({
                "payment_id": r["payment_id"],
                "customer_id": r["customer_id"],
                "event_type": "initial_processing",
                "attempt_number": 1,
                "sim_timestamp": r["failure_timestamp"],
                "action_type": action_node,
                "bandit_recommended_action": None,
                "actual_action": action_node,
                "downgrade_reason": None,
                "gate_mode": gate.get("mode", "auto_approve"),
                "gate_approved": True,
                "compliance_notes": [],
                "outcome_success": audit.get("success", False),
                "amount_recovered": audit.get("amount_recovered", 0.0),
                "action_cost": audit.get("action_cost", 0.0),
                "outcome_details": outcome.get("details", ""),
                "timing_context": None,
            })

            logger.log_summary({
                "payment_id": r["payment_id"],
                "customer_id": r["customer_id"],
                "amount": r["amount"],
                "payment_method": r["payment_method"],
                "payment_category": r["payment_category"],
                "bank_name": r["bank_name"],
                "failure_timestamp": r["failure_timestamp"],
                "failure_reason_code": r["failure_reason_code"],
                "diagnosed_cause": diag.get("cause", "unknown"),
                "diagnosis_confidence": diag.get("confidence", 0),
                "ground_truth_cause": r["ground_truth_cause"],
                "is_retryable": False,
                "total_attempts": 1,
                "final_outcome": outcome_label,
                "total_amount_recovered": audit.get("amount_recovered", 0.0),
                "total_action_cost": audit.get("action_cost", 0.0),
                "net_recovered": audit.get("amount_recovered", 0.0) - audit.get("action_cost", 0.0),
                "resolution_sim_timestamp": r["failure_timestamp"],
                "attempt_history": [{
                    "attempt": 1,
                    "action": action_node,
                    "outcome": "success" if audit.get("success") else "completed",
                    "time": r["failure_timestamp"],
                    "cost": audit.get("action_cost", 0.0),
                }],
            })
            continue

        # Retryable: schedule first attempt
        diagnosis_cache[r["payment_id"]] = diag
        cause = diag["cause"]
        action = decision["action_type"]
        payment_method = r["payment_method"]
        failure_time = datetime.fromisoformat(r["failure_timestamp"])

        clock.set(failure_time)

        delay_hours = 6.0
        scheduled_time = failure_time + timedelta(hours=delay_hours)

        if payment_method == "upi_autopay":
            from decision.scheduler import _enforce_upi_spacing, _clamp_upi_time
            from decision.constraints import clamp_upi_call
            min_hours = UPI_ATTEMPT_MIN_HOURS.get(1, 24)
            scheduled_time = failure_time + timedelta(hours=max(delay_hours, min_hours))
            scheduled_time = _enforce_upi_spacing(scheduled_time, failure_time, 1)
            if action == "call_then_retry":
                scheduled_time = clamp_upi_call(scheduled_time)
            else:
                scheduled_time = _clamp_upi_time(scheduled_time)
        else:
            if action == "call_then_retry":
                from decision.constraints import clamp_call_to_rbi_hours
                scheduled_time = clamp_call_to_rbi_hours(scheduled_time)

        event_queue.enqueue(
            event_type="retry_attempt",
            scheduled_time=scheduled_time,
            payload={
                "payment_id": r["payment_id"],
                "cause": cause,
                "action_type": action,
                "attempt_number": 1,
                "action_cost": ACTION_COSTS.get(action, 0.0),
                "payment_method": payment_method,
            },
        )

        compliance_notes = []
        for v in gate.get("compliance_violations", []):
            compliance_notes.append(v.get("details", ""))

        logger.log_event({
            "payment_id": r["payment_id"],
            "customer_id": r["customer_id"],
            "event_type": "initial_processing",
            "attempt_number": 0,
            "sim_timestamp": r["failure_timestamp"],
            "action_type": "scheduled",
            "bandit_recommended_action": constraint.get("original_action", action),
            "actual_action": action,
            "downgrade_reason": constraint.get("downgrade_reason") or constraint.get("reason"),
            "gate_mode": gate.get("mode", "auto_approve"),
            "gate_approved": True,
            "compliance_notes": compliance_notes,
            "outcome_success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "outcome_details": f"retry scheduled at {scheduled_time.isoformat()}",
            "timing_context": None,
        })

        retryable_scheduled += 1

    print(f"  Non-retryable resolved: {len(non_retryable_results)}")
    print(f"  Gate-blocked:           {len(gate_blocked_results)}")
    print(f"  Retryable scheduled:    {retryable_scheduled}")

    # ── Phase 2: SimClock driver loop ──
    print(f"\n── Phase 2: SimClock driver loop ──")

    retry_results = []
    events_by_day = defaultdict(lambda: {"events": 0, "successes": 0, "scheduled": 0})
    total_events = 0

    while True:
        event = event_queue.pop_next()
        if event is None:
            break

        scheduled_time = event["scheduled_time"]
        if isinstance(scheduled_time, str):
            scheduled_time = datetime.fromisoformat(scheduled_time)

        clock.set(scheduled_time)
        total_events += 1

        day_key = scheduled_time.strftime("%Y-%m-%d")
        events_by_day[day_key]["events"] += 1

        result = process_retry_event(
            event=event,
            payment_records=record_map,
            bandit=bandit,
            constraint_tracker=constraint_tracker,
            event_queue=event_queue,
            clock=clock,
            rng=rng,
            history=history,
        )

        retry_results.append(result)

        payload = event["payload"]
        pid = payload["payment_id"]
        r = record_map[pid]
        failure_time = datetime.fromisoformat(r["failure_timestamp"])
        days_since = (scheduled_time - failure_time).total_seconds() / 86400
        payday_dist = scheduled_time.day - 1

        logger.log_event({
            "payment_id": pid,
            "customer_id": r["customer_id"],
            "event_type": "retry_attempt" if result["status"] != "escalated" else "escalation_after_exhaustion",
            "attempt_number": result["attempt_number"],
            "sim_timestamp": scheduled_time.isoformat(),
            "action_type": payload["action_type"],
            "bandit_recommended_action": payload["action_type"],
            "actual_action": payload["action_type"],
            "downgrade_reason": None,
            "gate_mode": "auto_approve",
            "gate_approved": True,
            "compliance_notes": [],
            "outcome_success": result["status"] == "recovered",
            "amount_recovered": result["amount_recovered"],
            "action_cost": result["action_cost"],
            "outcome_details": f"{result['status']} on attempt {result['attempt_number']}",
            "timing_context": {
                "days_since_failure": round(days_since, 1),
                "days_since_payday": payday_dist,
                "time_of_day": scheduled_time.hour,
            },
        })

        if result["status"] == "recovered":
            events_by_day[day_key]["successes"] += 1
            _log_retryable_summary(logger, r, history[pid], "recovered", scheduled_time, diagnosis_cache.get(pid))
        elif result["status"] == "escalated":
            _log_retryable_summary(logger, r, history[pid], "failed_exhausted", scheduled_time, diagnosis_cache.get(pid))
        elif result["status"] == "scheduled_next":
            events_by_day[day_key]["scheduled"] += 1

    print(f"  Total retry events processed: {total_events}")
    print(f"  Simulated days: {len(events_by_day)}")

    # Flush audit data
    n_events, n_summaries = logger.flush_to_json()
    stats = logger.stats()
    print(f"\n  Logged {stats['events_logged']} events and {stats['summaries_logged']} payment summaries to {stats['backend']}")

    # ── Aggregate results ──
    total_at_risk = sum(r["amount"] for r in records)

    nr_recovered = sum(
        s.get("audit_entry", {}).get("amount_recovered", 0.0)
        for s in non_retryable_results
    )
    nr_cost = sum(
        s.get("audit_entry", {}).get("action_cost", 0.0)
        for s in non_retryable_results
    )

    retry_recovered = sum(r["amount_recovered"] for r in retry_results)
    retry_cost = sum(r["action_cost"] for r in retry_results)

    total_recovered = nr_recovered + retry_recovered
    total_cost = nr_cost + retry_cost
    net_recovered = total_recovered - total_cost

    attempt_resolution = Counter()
    for pid, attempts in history.items():
        last = attempts[-1]
        if last["outcome"] == "success":
            attempt_resolution[f"attempt_{last['attempt']}"] += 1
        else:
            attempt_resolution["escalated"] += 1

    for s in non_retryable_results:
        node = s.get("audit_entry", {}).get("action_node", "")
        attempt_resolution[f"non_retryable_{node}"] += 1

    for s in gate_blocked_results:
        attempt_resolution["gate_blocked"] += 1

    single_pass_recovered = 2_080_292.08

    # ── Print results ──
    print(f"\n{'═' * 70}")
    print(f"{'MULTI-ATTEMPT BATCH RESULTS — 500 PAYMENT RECORDS':^70s}")
    print(f"{'═' * 70}")

    print(f"\n── Financial Summary ──")
    print(f"  Total ₹ at risk:      {total_at_risk:>14,.2f}")
    print(f"  Non-retry recovered:  {nr_recovered:>14,.2f}")
    print(f"  Retry recovered:      {retry_recovered:>14,.2f}")
    print(f"  Total ₹ recovered:    {total_recovered:>14,.2f}")
    print(f"  Total action costs:   {total_cost:>14,.2f}")
    print(f"  Net ₹ recovered:      {net_recovered:>14,.2f}")
    print(f"  Recovery rate:        {net_recovered/total_at_risk:>13.1%}")

    print(f"\n── Single-Pass vs Multi-Attempt ──")
    print(f"  Single-pass net:      {single_pass_recovered:>14,.2f}")
    print(f"  Multi-attempt net:    {net_recovered:>14,.2f}")
    uplift = ((net_recovered - single_pass_recovered) / single_pass_recovered) * 100
    print(f"  Uplift:               {uplift:>+13.1f}%")

    print(f"\n── Attempt Distribution (Retryable Payments Only) ──")
    for key in ["attempt_1", "attempt_2", "attempt_3", "escalated"]:
        count = attempt_resolution.get(key, 0)
        if count > 0:
            print(f"  {key:<20s} {count:>5d}")
    total_retryable = sum(attempt_resolution.get(k, 0) for k in ["attempt_1", "attempt_2", "attempt_3", "escalated"])
    if total_retryable > 0:
        a1 = attempt_resolution.get("attempt_1", 0)
        a2 = attempt_resolution.get("attempt_2", 0)
        a3 = attempt_resolution.get("attempt_3", 0)
        esc = attempt_resolution.get("escalated", 0)
        print(f"  ─────────────────────────")
        print(f"  Total retryable:     {total_retryable:>5d}")
        print(f"  Resolved by retry:   {a1+a2+a3:>5d} ({(a1+a2+a3)/total_retryable:.1%})")
        print(f"  Escalated:           {esc:>5d} ({esc/total_retryable:.1%})")

    print(f"\n── Non-Retryable Resolution ──")
    for key in sorted(attempt_resolution):
        if key.startswith("non_retryable_"):
            node = key.replace("non_retryable_", "")
            print(f"  {node:<25s} {attempt_resolution[key]:>5d}")
    if attempt_resolution.get("gate_blocked", 0) > 0:
        print(f"  {'gate_blocked':<25s} {attempt_resolution['gate_blocked']:>5d}")

    print(f"\n── Timeline (by simulated day) ──")
    print(f"  {'Day':<14s} {'Events':>7s} {'Successes':>10s} {'Scheduled':>10s}")
    print(f"  {'─' * 41}")
    for day in sorted(events_by_day.keys()):
        d = events_by_day[day]
        print(f"  {day:<14s} {d['events']:>7d} {d['successes']:>10d} {d['scheduled']:>10d}")

    # ── Sample traces ──
    print(f"\n{'═' * 70}")
    print(f"{'SAMPLE MULTI-ATTEMPT TRACES':^70s}")
    print(f"{'═' * 70}")

    multi_attempt_pids = [
        pid for pid, attempts in history.items()
        if len(attempts) >= 2 and attempts[-1]["outcome"] == "success"
    ]

    trace_pids = multi_attempt_pids[:3] if multi_attempt_pids else []
    if not trace_pids:
        for pid in list(history.keys()):
            if len(history[pid]) >= 2:
                trace_pids = [pid]
                break

    for pid in trace_pids:
        r = record_map[pid]
        attempts = history[pid]
        print(f"\n┌─ {pid} ─────────────────────────────────────────────")
        print(f"│ Payment: ₹{r['amount']:,.2f} | {r['payment_method']} | "
              f"{r['payment_category']} | {r['bank_name']}")
        print(f"│ Failure: {r['failure_timestamp']} | code={r['failure_reason_code']}")
        print(f"│ Ground truth: {r['ground_truth_cause']}")
        print(f"│")
        for a in attempts:
            marker = "✓" if a["outcome"] == "success" else "✗"
            print(f"│  {marker} Attempt {a['attempt']} @ {a['time']}")
            print(f"│    action={a['action']} → {a['outcome']}")
            if a["recovered"] > 0:
                print(f"│    recovered=₹{a['recovered']:,.2f} cost=₹{a['cost']:.2f}")
            else:
                print(f"│    cost=₹{a['cost']:.2f}")
        print(f"└──────────────────────────────────────────────────────")

    return {
        "total_at_risk": total_at_risk,
        "total_recovered": total_recovered,
        "total_cost": total_cost,
        "net_recovered": net_recovered,
        "history": history,
        "attempt_resolution": dict(attempt_resolution),
    }


def _log_retryable_summary(logger, record, attempts, final_outcome, resolution_time, diag=None):
    total_recovered = sum(a.get("recovered", 0.0) for a in attempts)
    total_cost = sum(a.get("cost", 0.0) for a in attempts)
    diag = diag or {}

    logger.log_summary({
        "payment_id": record["payment_id"],
        "customer_id": record["customer_id"],
        "amount": record["amount"],
        "payment_method": record["payment_method"],
        "payment_category": record["payment_category"],
        "bank_name": record["bank_name"],
        "failure_timestamp": record["failure_timestamp"],
        "failure_reason_code": record["failure_reason_code"],
        "diagnosed_cause": diag.get("cause", attempts[0].get("cause", "unknown") if attempts else "unknown"),
        "diagnosis_confidence": diag.get("confidence", 0.0),
        "ground_truth_cause": record["ground_truth_cause"],
        "is_retryable": True,
        "total_attempts": len(attempts),
        "final_outcome": final_outcome,
        "total_amount_recovered": total_recovered,
        "total_action_cost": total_cost,
        "net_recovered": total_recovered - total_cost,
        "resolution_sim_timestamp": resolution_time.isoformat(),
        "attempt_history": attempts,
    })


if __name__ == "__main__":
    run()
