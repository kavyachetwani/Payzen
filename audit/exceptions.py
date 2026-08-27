"""Exception list: categorized unrecovered payments from audit data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit.logger import load_from_fallback


RECOVERY_SUGGESTIONS = {
    "mandate_revoked": "customer conversation — understand cancellation reason, offer re-enrollment",
    "mandate_expired": "mandate re-registration — auto-initiated, awaiting customer e-sign",
    "card_expired": "card update link sent — awaiting customer action",
    "afa_stuck": "customer auth nudge — guide through AFA verification flow",
    "ambiguous": "human investigation — review transaction logs for root cause",
    "insufficient_funds": "near-payday retry or gentle payment reminder",
    "bank_outage": "re-attempt after bank systems stabilize",
}


def run():
    _, summaries = load_from_fallback()

    if not summaries:
        print("No audit data found. Run action/run_batch_multi.py first.")
        return

    exhausted = [s for s in summaries if s["final_outcome"] == "failed_exhausted"]
    blocked = [s for s in summaries if s["final_outcome"] == "gate_blocked"]
    escalated = [s for s in summaries if s["final_outcome"] == "escalated"]
    pending_nr = [s for s in summaries if s["final_outcome"] in ("card_update_sent", "mandate_resequenced")]

    print(f"{'═' * 70}")
    print(f"{'EXCEPTION LIST — UNRECOVERED PAYMENTS':^70s}")
    print(f"{'═' * 70}")

    # 1. Exhausted retries
    print(f"\n── 1. Exhausted Retries ({len(exhausted)} payments, ₹{sum(s['amount'] for s in exhausted):,.2f} at risk) ──")
    if not exhausted:
        print("  None.")
    for s in exhausted[:10]:
        print(f"\n  {s['payment_id']} | ₹{s['amount']:,.2f} | {s['diagnosed_cause']} | {s['payment_method']}")
        for a in s.get("attempt_history", []):
            marker = "✓" if a.get("outcome") == "success" else "✗"
            print(f"    {marker} Attempt {a['attempt']} @ {a['time']} | {a['action']} → {a['outcome']} | cost=₹{a.get('cost', 0):.2f}")
        suggestion = RECOVERY_SUGGESTIONS.get(s["diagnosed_cause"], "manual review")
        print(f"    → Suggested: {suggestion}")
    if len(exhausted) > 10:
        print(f"\n  ... and {len(exhausted) - 10} more")

    # 2. Gate-blocked
    print(f"\n── 2. Gate-Blocked ({len(blocked)} payments, ₹{sum(s['amount'] for s in blocked):,.2f} at risk) ──")
    if not blocked:
        print("  None.")
    for s in blocked:
        print(f"\n  {s['payment_id']} | ₹{s['amount']:,.2f} | {s['diagnosed_cause']}")
        hist = s.get("attempt_history", [{}])
        if hist:
            details = hist[0].get("details", "compliance violation")
            print(f"    Reason: {details}")
        has_contactless = s["diagnosed_cause"] in ("insufficient_funds", "bank_outage")
        if has_contactless:
            print(f"    → Contactless auto_retry could be attempted")
        else:
            print(f"    → No contactless alternative — requires manual outreach")

    # 3. Escalated directly
    print(f"\n── 3. Escalated Directly ({len(escalated)} payments, ₹{sum(s['amount'] for s in escalated):,.2f} at risk) ──")
    if not escalated:
        print("  None.")
    cause_groups = {}
    for s in escalated:
        cause = s["diagnosed_cause"]
        if cause not in cause_groups:
            cause_groups[cause] = []
        cause_groups[cause].append(s)
    for cause, items in sorted(cause_groups.items(), key=lambda x: -len(x[1])):
        total_risk = sum(s["amount"] for s in items)
        suggestion = RECOVERY_SUGGESTIONS.get(cause, "manual review")
        print(f"\n  {cause} ({len(items)} payments, ₹{total_risk:,.2f})")
        print(f"    → {suggestion}")
        for s in items[:3]:
            print(f"      {s['payment_id']} | ₹{s['amount']:,.2f} | {s['bank_name']}")
        if len(items) > 3:
            print(f"      ... and {len(items) - 3} more")

    # 4. Non-retryable pending
    print(f"\n── 4. Non-Retryable Pending ({len(pending_nr)} payments, ₹{sum(s['amount'] for s in pending_nr):,.2f} at risk) ──")
    if not pending_nr:
        print("  None.")
    outcome_groups = {}
    for s in pending_nr:
        outcome = s["final_outcome"]
        if outcome not in outcome_groups:
            outcome_groups[outcome] = []
        outcome_groups[outcome].append(s)
    for outcome, items in sorted(outcome_groups.items()):
        total_risk = sum(s["amount"] for s in items)
        if outcome == "card_update_sent":
            timeline = "7-14 days for customer to update card details"
        else:
            timeline = "3-5 business days for mandate re-registration"
        print(f"\n  {outcome} ({len(items)} payments, ₹{total_risk:,.2f})")
        print(f"    Expected resolution: {timeline}")
        for s in items[:3]:
            print(f"      {s['payment_id']} | ₹{s['amount']:,.2f} | {s['bank_name']}")
        if len(items) > 3:
            print(f"      ... and {len(items) - 3} more")

    # Honest summary
    all_unresolved = exhausted + blocked + escalated + pending_nr
    total_unresolved = len(all_unresolved)
    total_risk = sum(s["amount"] for s in all_unresolved)

    print(f"\n{'═' * 70}")
    print(f"  {total_unresolved} cases representing ₹{total_risk:,.2f} remain unresolved.")
    print(f"  Breakdown:")
    print(f"    Exhausted retries:        {len(exhausted):>4d} (₹{sum(s['amount'] for s in exhausted):>12,.2f})")
    print(f"    Gate-blocked:             {len(blocked):>4d} (₹{sum(s['amount'] for s in blocked):>12,.2f})")
    print(f"    Escalated:                {len(escalated):>4d} (₹{sum(s['amount'] for s in escalated):>12,.2f})")
    print(f"    Pending non-retryable:    {len(pending_nr):>4d} (₹{sum(s['amount'] for s in pending_nr):>12,.2f})")
    print(f"{'═' * 70}")


if __name__ == "__main__":
    run()
