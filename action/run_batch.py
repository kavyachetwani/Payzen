"""Batch runner: process all 500 payment records through the LangGraph pipeline."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from action.graph import build_graph
from action.nodes import reset_globals
from action.compliance import get_dnd_set, reset_dnd

DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"

SAMPLE_IDS = ["PAY_00002", "PAY_00010", "PAY_00014"]


def run(auto_approve: bool = True):
    records = json.loads(DATA_PATH.read_text())
    print(f"Loading {len(records)} payment records...")
    print(f"Mode: {'auto-approve' if auto_approve else 'interactive (require_approval pauses)'}")

    reset_globals()
    reset_dnd()
    app = build_graph()

    dnd_set = get_dnd_set()
    print(f"DND customers: {len(dnd_set)} ({len(dnd_set)/len(set(r['customer_id'] for r in records)):.1%})")
    print("Graph compiled. Running batch...\n")

    results = []
    traces = {}
    dnd_blocked_trace = None

    for r in records:
        initial_state = {
            "payment_id": r["payment_id"],
            "customer_id": r["customer_id"],
            "payment_method": r["payment_method"],
            "amount": r["amount"],
            "payment_record": r,
        }

        final_state = app.invoke(initial_state)
        results.append(final_state)

        if r["payment_id"] in SAMPLE_IDS:
            traces[r["payment_id"]] = final_state

        gate = final_state.get("gate_result", {})
        if (dnd_blocked_trace is None
                and not gate.get("approved", True)
                and any(v.get("check") == "dnd" for v in gate.get("compliance_violations", []))):
            dnd_blocked_trace = (r, final_state)

    node_counts = Counter()
    retry_success = 0
    retry_failure = 0
    total_recovered = 0.0
    total_cost = 0.0
    total_at_risk = sum(r["amount"] for r in records)

    non_retry_counts = defaultdict(int)
    cause_stats = defaultdict(lambda: {"count": 0, "recovered": 0.0, "cost": 0.0})

    gate_mode_counts = Counter()
    gate_blocked_count = 0
    compliance_violation_counts = Counter()
    dnd_block_count = 0
    pre_debit_force_count = 0
    contact_hours_violations = 0
    contact_limit_violations = 0

    for state in results:
        audit = state.get("audit_entry", {})
        node = audit.get("action_node", "unknown")
        node_counts[node] += 1

        recovered = audit.get("amount_recovered", 0.0)
        cost = audit.get("action_cost", 0.0)
        total_recovered += recovered
        total_cost += cost

        cause = state.get("diagnosis", {}).get("cause", "unknown")
        cause_stats[cause]["count"] += 1
        cause_stats[cause]["recovered"] += recovered
        cause_stats[cause]["cost"] += cost

        if node == "auto_retry":
            if audit.get("success"):
                retry_success += 1
            else:
                retry_failure += 1
        elif node != "gate_blocked":
            non_retry_counts[node] += 1

        gate = state.get("gate_result", {})
        gate_mode_counts[gate.get("mode", "unknown")] += 1

        if not gate.get("approved", True):
            gate_blocked_count += 1

        for v in gate.get("compliance_violations", []):
            compliance_violation_counts[v.get("check", "unknown")] += 1
            if v.get("check") == "dnd":
                if v.get("remedy") == "block":
                    dnd_block_count += 1
                else:
                    dnd_block_count += 0
            elif v.get("check") == "pre_debit":
                pre_debit_force_count += 1
            elif v.get("check") == "contact_hours":
                contact_hours_violations += 1
            elif v.get("check") == "contact_limits":
                contact_limit_violations += 1

    dnd_total = sum(1 for s in results
                    for v in s.get("gate_result", {}).get("compliance_violations", [])
                    if v.get("check") == "dnd")

    net_recovered = total_recovered - total_cost

    print(f"{'═' * 65}")
    print(f"{'BATCH RESULTS — 500 PAYMENT RECORDS':^65s}")
    print(f"{'═' * 65}")

    print(f"\n── Gate Summary ──")
    for mode in ["auto_approve", "require_approval", "reject"]:
        count = gate_mode_counts.get(mode, 0)
        print(f"  {mode:<25s} {count:>5d} ({count/len(records):.1%})")
    print(f"  {'gate_blocked':<25s} {gate_blocked_count:>5d}")

    print(f"\n── Compliance Checks ──")
    print(f"  DND blocks (total):     {dnd_total:>5d}")
    print(f"  DND → rejected:         {gate_blocked_count:>5d}")
    print(f"  Pre-debit → forced SMS: {pre_debit_force_count:>5d}")
    print(f"  Contact hours safety:   {contact_hours_violations:>5d}  {'✓ 0 violations' if contact_hours_violations == 0 else '⚠ violations detected!'}")
    print(f"  Contact limits safety:  {contact_limit_violations:>5d}  {'✓ 0 violations' if contact_limit_violations == 0 else '⚠ violations detected!'}")

    print(f"\n── Action Node Distribution ──")
    for node in ["auto_retry", "card_update_link", "mandate_resequence", "escalation", "gate_blocked"]:
        count = node_counts.get(node, 0)
        print(f"  {node:<25s} {count:>5d} ({count/len(records):.1%})")

    print(f"\n── Retry Outcomes ──")
    retry_total = retry_success + retry_failure
    if retry_total > 0:
        print(f"  Success: {retry_success:>5d} ({retry_success/retry_total:.1%})")
        print(f"  Failure: {retry_failure:>5d} ({retry_failure/retry_total:.1%})")
    else:
        print(f"  No retries executed.")

    print(f"\n── Financial Summary ──")
    print(f"  Total ₹ at risk:    {total_at_risk:>14,.2f}")
    print(f"  Total ₹ recovered:  {total_recovered:>14,.2f}")
    print(f"  Total action costs: {total_cost:>14,.2f}")
    print(f"  Net ₹ recovered:    {net_recovered:>14,.2f}")
    print(f"  Recovery rate:      {net_recovered/total_at_risk:>13.1%}")

    print(f"\n── By Cause ──")
    print(f"  {'Cause':<22s} {'Count':>5s} {'Recovered':>12s} {'Cost':>8s} {'Net':>12s}")
    print(f"  {'─' * 59}")
    for cause in sorted(cause_stats, key=lambda c: -cause_stats[c]["recovered"]):
        s = cause_stats[cause]
        net = s["recovered"] - s["cost"]
        print(f"  {cause:<22s} {s['count']:>5d} {s['recovered']:>11,.2f} {s['cost']:>7,.2f} {net:>11,.2f}")

    print(f"\n{'═' * 65}")
    print(f"{'SAMPLE TRACES':^65s}")
    print(f"{'═' * 65}")

    record_map = {r["payment_id"]: r for r in records}

    for pid in SAMPLE_IDS:
        if pid not in traces:
            continue
        state = traces[pid]
        r = record_map[pid]
        _print_trace(r, state)

    if dnd_blocked_trace:
        r, state = dnd_blocked_trace
        print(f"\n{'═' * 65}")
        print(f"{'DND-BLOCKED TRACE':^65s}")
        print(f"{'═' * 65}")
        _print_trace(r, state)

    return results


def _print_trace(r, state):
    pid = r["payment_id"]
    print(f"\n┌─ {pid} ─────────────────────────────────────────────")
    print(f"│ Payment: ₹{r['amount']:,.2f} | {r['payment_method']} | "
          f"{r['payment_category']} | {r['bank_name']}")
    print(f"│ Failure: {r['failure_timestamp']} | code={r['failure_reason_code']}")
    print(f"│")

    diag = state.get("diagnosis", {})
    print(f"│ → Diagnosis: cause={diag.get('cause')} "
          f"(confidence={diag.get('confidence', 0):.2f})")
    print(f"│   [ground truth: {r['ground_truth_cause']}]")

    dec = state.get("decision", {})
    print(f"│ → Decision: retryable={dec.get('is_retryable')} "
          f"action={dec.get('action_type')} "
          f"route={dec.get('route_to')}")

    con = state.get("constraint_result", {})
    if con.get("downgrade_reason"):
        print(f"│   ⚠ Downgraded: {con['original_action']} → {con['actual_action']} "
              f"({con['downgrade_reason']})")

    gate = state.get("gate_result", {})
    mode = gate.get("mode", "?")
    approved = gate.get("approved", "?")
    print(f"│ → Gate: mode={mode} approved={approved}")
    if gate.get("compliance_violations"):
        for v in gate["compliance_violations"]:
            print(f"│   ⚠ {v.get('check')}: {v.get('details')}")
    if gate.get("original_action") != gate.get("final_action"):
        print(f"│   Action changed: {gate.get('original_action')} → {gate.get('final_action')}")

    outcome = state.get("action_outcome", {})
    audit = state.get("audit_entry", {})
    node = audit.get("action_node", "?")
    print(f"│ → Action [{node}]: {outcome.get('details', '?')}")
    print(f"│   Recovered: ₹{outcome.get('amount_recovered', 0):,.2f} | "
          f"Cost: ₹{outcome.get('action_cost', 0):,.2f}")
    print(f"└──────────────────────────────────────────────────────")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch recovery pipeline runner")
    parser.add_argument("--auto-approve", action="store_true", default=True,
                        help="Auto-approve all require_approval actions (default: True)")
    parser.add_argument("--interactive", action="store_true",
                        help="Pause on require_approval actions (not implemented yet)")
    args = parser.parse_args()
    run(auto_approve=not args.interactive)
