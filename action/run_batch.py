"""Batch runner: process all 500 payment records through the LangGraph pipeline."""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from action.graph import build_graph
from action.nodes import reset_globals

DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"

SAMPLE_IDS = ["PAY_00002", "PAY_00010", "PAY_00014"]


def run():
    records = json.loads(DATA_PATH.read_text())
    print(f"Loading {len(records)} payment records...")

    reset_globals()
    app = build_graph()
    print("Graph compiled. Running batch...\n")

    results = []
    traces = {}

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

    node_counts = Counter()
    retry_success = 0
    retry_failure = 0
    total_recovered = 0.0
    total_cost = 0.0
    total_at_risk = sum(r["amount"] for r in records)

    non_retry_counts = defaultdict(int)
    cause_stats = defaultdict(lambda: {"count": 0, "recovered": 0.0, "cost": 0.0})

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
        else:
            non_retry_counts[node] += 1

    net_recovered = total_recovered - total_cost

    print(f"{'═' * 65}")
    print(f"{'BATCH RESULTS — 500 PAYMENT RECORDS':^65s}")
    print(f"{'═' * 65}")

    print(f"\n── Action Node Distribution ──")
    for node in ["auto_retry", "card_update_link", "mandate_resequence", "escalation"]:
        count = node_counts.get(node, 0)
        print(f"  {node:<25s} {count:>5d} ({count/len(records):.1%})")

    print(f"\n── Retry Outcomes ──")
    retry_total = retry_success + retry_failure
    if retry_total > 0:
        print(f"  Success: {retry_success:>5d} ({retry_success/retry_total:.1%})")
        print(f"  Failure: {retry_failure:>5d} ({retry_failure/retry_total:.1%})")
    else:
        print(f"  No retries executed.")

    print(f"\n── Non-Retryable Actions ──")
    for node in ["card_update_link", "mandate_resequence", "escalation"]:
        count = non_retry_counts.get(node, 0)
        if count > 0:
            print(f"  {node}: {count}")

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

        outcome = state.get("action_outcome", {})
        audit = state.get("audit_entry", {})
        node = audit.get("action_node", "?")
        print(f"│ → Action [{node}]: {outcome.get('details', '?')}")
        print(f"│   Recovered: ₹{outcome.get('amount_recovered', 0):,.2f} | "
              f"Cost: ₹{outcome.get('action_cost', 0):,.2f}")
        print(f"└──────────────────────────────────────────────────────")

    return results


if __name__ == "__main__":
    run()
