"""Multi-attempt batch runner: retries play out across simulated time via SimClock.

Phase 1: Initial processing — non-retryable resolved immediately, retryable scheduled
Phase 2: SimClock driver loop — retry events execute in chronological order
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
    process_retry_event, reset_success_rates, _days_since_payday,
    _load_success_rates,
)

from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS
from decision.constraints import ConstraintTracker
from decision.stopping import check_stop, UPI_ATTEMPT_MIN_HOURS
from decision.policy import is_retryable, max_attempts

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


def run():
    records = json.loads(DATA_PATH.read_text())
    record_map = {r["payment_id"]: r for r in records}
    print(f"Loading {len(records)} payment records...")

    reset_globals()
    reset_dnd()
    reset_success_rates()

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
    history = {}  # payment_id -> list of attempt entries

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

        if not gate.get("approved", True):
            gate_blocked_results.append(final_state)
            continue

        if not decision.get("is_retryable", False) and decision.get("route_to") != None:
            non_retryable_results.append(final_state)
            continue

        if not decision.get("is_retryable", False):
            non_retryable_results.append(final_state)
            continue

        # Retryable: schedule first attempt
        cause = final_state["diagnosis"]["cause"]
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

        if result["status"] == "recovered":
            events_by_day[day_key]["successes"] += 1
        elif result["status"] == "scheduled_next":
            events_by_day[day_key]["scheduled"] += 1

    print(f"  Total retry events processed: {total_events}")
    print(f"  Simulated days: {len(events_by_day)}")

    # ── Aggregate results ──
    total_at_risk = sum(r["amount"] for r in records)

    # Non-retryable financials
    nr_recovered = sum(
        s.get("audit_entry", {}).get("amount_recovered", 0.0)
        for s in non_retryable_results
    )
    nr_cost = sum(
        s.get("audit_entry", {}).get("action_cost", 0.0)
        for s in non_retryable_results
    )

    # Retry financials
    retry_recovered = sum(r["amount_recovered"] for r in retry_results)
    retry_cost = sum(r["action_cost"] for r in retry_results)

    total_recovered = nr_recovered + retry_recovered
    total_cost = nr_cost + retry_cost
    net_recovered = total_recovered - total_cost

    # Attempt distribution
    attempt_resolution = Counter()
    for pid, attempts in history.items():
        last = attempts[-1]
        if last["outcome"] == "success":
            attempt_resolution[f"attempt_{last['attempt']}"] += 1
        else:
            attempt_resolution["escalated"] += 1

    # For payments that never entered history (non-retryable)
    for s in non_retryable_results:
        node = s.get("audit_entry", {}).get("action_node", "")
        attempt_resolution[f"non_retryable_{node}"] += 1

    for s in gate_blocked_results:
        attempt_resolution["gate_blocked"] += 1

    # Single-pass comparison
    single_pass_recovered = 2_080_292.08  # from Stage 6 run

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

    if multi_attempt_pids:
        for pid in multi_attempt_pids[:3]:
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
    else:
        print("\n  (No multi-attempt successes found — showing first multi-attempt payment)")
        for pid in list(history.keys())[:3]:
            if len(history[pid]) >= 2:
                r = record_map[pid]
                attempts = history[pid]
                print(f"\n┌─ {pid} ─────────────────────────────────────────────")
                print(f"│ Payment: ₹{r['amount']:,.2f} | {r['payment_method']} | "
                      f"{r['payment_category']} | {r['bank_name']}")
                print(f"│ Failure: {r['failure_timestamp']} | code={r['failure_reason_code']}")
                print(f"│")
                for a in attempts:
                    marker = "✓" if a["outcome"] == "success" else "✗"
                    print(f"│  {marker} Attempt {a['attempt']} @ {a['time']}")
                    print(f"│    action={a['action']} → {a['outcome']} cost=₹{a['cost']:.2f}")
                    if a["recovered"] > 0:
                        print(f"│    recovered=₹{a['recovered']:,.2f}")
                print(f"└──────────────────────────────────────────────────────")
                break

    return {
        "total_at_risk": total_at_risk,
        "total_recovered": total_recovered,
        "total_cost": total_cost,
        "net_recovered": net_recovered,
        "history": history,
        "attempt_resolution": dict(attempt_resolution),
    }


if __name__ == "__main__":
    run()
