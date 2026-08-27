"""Financial metrics report from audit data.

Reads from audit_summary and audit_events (Firestore or fallback JSON).
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit.logger import load_from_fallback


SINGLE_PASS_NET = 2_080_292.08


def run():
    events, summaries = load_from_fallback()

    if not summaries:
        print("No audit data found. Run action/run_batch_multi.py first.")
        return

    total_at_risk = sum(s["amount"] for s in summaries)
    total_recovered = sum(s["total_amount_recovered"] for s in summaries)
    total_cost = sum(s["total_action_cost"] for s in summaries)
    net_recovered = total_recovered - total_cost

    print(f"{'═' * 70}")
    print(f"{'FINANCIAL METRICS REPORT':^70s}")
    print(f"{'═' * 70}")

    # 1-5: Headline financials
    print(f"\n── 1. Headline Financials ──")
    print(f"  Total ₹ at risk:      {total_at_risk:>14,.2f}")
    print(f"  Total ₹ recovered:    {total_recovered:>14,.2f}")
    print(f"  Total action costs:   {total_cost:>14,.2f}")
    print(f"  Net ₹ recovered:      {net_recovered:>14,.2f}")
    print(f"  Net recovery rate:    {net_recovered/total_at_risk:>13.1%}")

    # 6: By cause
    cause_stats = defaultdict(lambda: {"count": 0, "recovered": 0.0, "cost": 0.0, "amount": 0.0})
    for s in summaries:
        c = s["diagnosed_cause"]
        cause_stats[c]["count"] += 1
        cause_stats[c]["recovered"] += s["total_amount_recovered"]
        cause_stats[c]["cost"] += s["total_action_cost"]
        cause_stats[c]["amount"] += s["amount"]

    print(f"\n── 6. By Diagnosed Cause ──")
    print(f"  {'Cause':<22s} {'Count':>5s} {'₹ Recovered':>13s} {'₹ Cost':>8s} {'Net':>13s} {'Rate':>7s}")
    print(f"  {'─' * 68}")
    for cause in sorted(cause_stats, key=lambda c: -cause_stats[c]["recovered"]):
        s = cause_stats[cause]
        net = s["recovered"] - s["cost"]
        rate = net / s["amount"] if s["amount"] > 0 else 0
        print(f"  {cause:<22s} {s['count']:>5d} {s['recovered']:>12,.2f} {s['cost']:>7,.2f} {net:>12,.2f} {rate:>6.1%}")

    # 7: By final outcome
    outcome_counts = Counter(s["final_outcome"] for s in summaries)
    print(f"\n── 7. By Final Outcome ──")
    for outcome in sorted(outcome_counts, key=lambda o: -outcome_counts[o]):
        count = outcome_counts[outcome]
        print(f"  {outcome:<30s} {count:>5d} ({count/len(summaries):.1%})")

    # 8: By action type (from events)
    action_stats = defaultdict(lambda: {"count": 0, "success": 0, "recovered": 0.0, "cost": 0.0})
    for e in events:
        at = e.get("action_type", e.get("actual_action", "unknown"))
        action_stats[at]["count"] += 1
        if e.get("outcome_success", False):
            action_stats[at]["success"] += 1
        action_stats[at]["recovered"] += e.get("amount_recovered", 0.0)
        action_stats[at]["cost"] += e.get("action_cost", 0.0)

    print(f"\n── 8. By Action Type (all events) ──")
    print(f"  {'Action':<25s} {'Count':>6s} {'Success%':>9s} {'₹ Recovered':>13s} {'₹ Cost':>8s}")
    print(f"  {'─' * 61}")
    for at in sorted(action_stats, key=lambda a: -action_stats[a]["count"]):
        s = action_stats[at]
        sr = s["success"] / s["count"] if s["count"] > 0 else 0
        print(f"  {at:<25s} {s['count']:>6d} {sr:>8.1%} {s['recovered']:>12,.2f} {s['cost']:>7,.2f}")

    # 9: Attempt analysis
    attempt_dist = Counter()
    for s in summaries:
        if not s["is_retryable"]:
            continue
        if s["final_outcome"] == "recovered":
            attempt_dist[f"attempt_{s['total_attempts']}"] += 1
        else:
            attempt_dist["escalated"] += 1

    print(f"\n── 9. Attempt Distribution (retryable only) ──")
    total_retryable = sum(attempt_dist.values())
    for key in ["attempt_1", "attempt_2", "attempt_3", "escalated"]:
        count = attempt_dist.get(key, 0)
        if count > 0 or key == "escalated":
            print(f"  {key:<20s} {count:>5d} ({count/total_retryable:.1%})" if total_retryable > 0 else f"  {key:<20s} {count:>5d}")

    # 10: Constraint impact
    downgraded = [e for e in events if e.get("downgrade_reason")]
    print(f"\n── 10. Constraint Impact ──")
    print(f"  Actions downgraded:   {len(downgraded)}")
    if downgraded:
        reason_counts = Counter(e["downgrade_reason"] for e in downgraded)
        for reason, count in reason_counts.most_common(5):
            print(f"    {reason}: {count}")

    # 11: Single-pass comparison
    print(f"\n── 11. Single-Pass vs Multi-Attempt ──")
    print(f"  Single-pass net:      {SINGLE_PASS_NET:>14,.2f}")
    print(f"  Multi-attempt net:    {net_recovered:>14,.2f}")
    uplift = ((net_recovered - SINGLE_PASS_NET) / SINGLE_PASS_NET) * 100
    print(f"  Uplift:               {uplift:>+13.1f}%")

    print(f"\n{'═' * 70}")


if __name__ == "__main__":
    run()
