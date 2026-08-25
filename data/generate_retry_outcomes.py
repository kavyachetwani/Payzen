"""Generate 1,200 synthetic retry outcome records with embedded learnable patterns.

Patterns the bandit should discover:
- insufficient_funds near payday → higher success
- bank_outage retried 6-12h later → high success
- card_expired / mandate_expired / mandate_revoked → almost never succeeds
- 3rd attempt → diminishing returns
- sms_then_retry for insufficient_funds → +10-15% over auto_retry
- call_then_retry → highest success but costly (₹15)
- pre_debit_notification_sent=False + insufficient_funds → higher recovery
  (customer didn't know debit was coming; notifying helps)

See /data/README.md for full spec.
"""

import json
import random
from pathlib import Path

SEED = 7
NUM_RECORDS = 1200
OUTPUT_PATH = Path(__file__).parent / "retry_outcomes.json"

CAUSES = [
    "insufficient_funds", "bank_outage", "mandate_expired",
    "mandate_revoked", "card_expired", "afa_stuck", "ambiguous",
]
CAUSE_WEIGHTS = [0.30, 0.20, 0.10, 0.05, 0.12, 0.13, 0.10]

ACTIONS = ["auto_retry", "sms_then_retry", "call_then_retry"]
ACTION_COSTS = {"auto_retry": 0.0, "sms_then_retry": 2.0, "call_then_retry": 15.0}

AMOUNT_RANGES = {
    "subscription": (99, 999),
    "emi":          (2000, 50000),
    "sip":          (500, 25000),
    "insurance":    (1000, 50000),
    "cc_bill":      (500, 80000),
}


def base_success_rate(cause: str, attempt: int) -> float:
    rates = {
        "insufficient_funds": 0.30,
        "bank_outage":        0.40,
        "mandate_expired":    0.04,
        "mandate_revoked":    0.02,
        "card_expired":       0.03,
        "afa_stuck":          0.15,
        "ambiguous":          0.20,
    }
    rate = rates[cause]
    if attempt == 2:
        rate *= 0.80
    elif attempt == 3:
        rate *= 0.60
    return rate


def compute_success_prob(cause, attempt, action, days_since_failure,
                         days_since_payday, time_of_day, amount,
                         pre_debit_notification_sent, rng):
    prob = base_success_rate(cause, attempt)

    if cause == "insufficient_funds" and 0 <= days_since_payday <= 3:
        prob += 0.30

    if cause == "insufficient_funds" and action == "sms_then_retry":
        prob += 0.12

    # No notification sent + insufficient_funds → higher recovery potential
    if cause == "insufficient_funds" and not pre_debit_notification_sent:
        prob += 0.10

    if cause == "bank_outage":
        if days_since_failure == 0 and 6 <= time_of_day <= 18:
            prob += 0.35
        elif days_since_failure == 1:
            prob += 0.25

    if action == "call_then_retry":
        prob += 0.15

    if cause == "afa_stuck" and action in ("sms_then_retry", "call_then_retry"):
        prob += 0.10

    prob += rng.gauss(0, 0.05)
    return max(0.01, min(0.95, prob))


def generate():
    rng = random.Random(SEED)
    records = []

    for i in range(NUM_RECORDS):
        cause = rng.choices(CAUSES, weights=CAUSE_WEIGHTS, k=1)[0]
        attempt = rng.choices([1, 2, 3], weights=[0.50, 0.30, 0.20], k=1)[0]
        action = rng.choice(ACTIONS)
        time_of_day = rng.randint(0, 23)
        day_of_week = rng.randint(0, 6)
        days_since_failure = rng.choices(
            range(0, 15),
            weights=[5, 4, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            k=1,
        )[0]
        days_since_payday = rng.randint(-15, 15)

        amt_type = rng.choices(
            ["subscription", "emi", "sip", "insurance", "cc_bill"],
            weights=[0.30, 0.35, 0.15, 0.10, 0.10],
            k=1,
        )[0]
        lo, hi = AMOUNT_RANGES[amt_type]
        amount = round(rng.uniform(lo, hi), 2)

        if cause == "mandate_revoked":
            pre_debit = rng.random() < 0.60
        else:
            pre_debit = rng.random() < 0.80

        prob = compute_success_prob(
            cause, attempt, action, days_since_failure,
            days_since_payday, time_of_day, amount, pre_debit, rng,
        )
        outcome = "success" if rng.random() < prob else "failure"

        records.append({
            "retry_id": f"RTR_{i + 1:05d}",
            "original_cause": cause,
            "retry_attempt_number": attempt,
            "time_of_day": time_of_day,
            "day_of_week": day_of_week,
            "days_since_failure": days_since_failure,
            "days_since_estimated_payday": days_since_payday,
            "amount": amount,
            "action_type": action,
            "action_cost": ACTION_COSTS[action],
            "pre_debit_notification_sent": pre_debit,
            "outcome": outcome,
            "amount_recovered": amount if outcome == "success" else 0.0,
        })

    OUTPUT_PATH.write_text(json.dumps(records, indent=2))
    print(f"Generated {len(records)} records → {OUTPUT_PATH}")
    print()
    _print_summary(records)
    return records


def _print_summary(records):
    from collections import Counter

    total = len(records)
    causes = Counter(r["original_cause"] for r in records)
    actions = Counter(r["action_type"] for r in records)
    outcomes = Counter(r["outcome"] for r in records)

    print("── Cause Distribution ──")
    for c in sorted(causes, key=causes.get, reverse=True):
        print(f"  {c:25s} {causes[c]:4d}  ({causes[c]/total*100:5.1f}%)")

    print("\n── Action Distribution ──")
    for a in sorted(actions, key=actions.get, reverse=True):
        print(f"  {a:25s} {actions[a]:4d}  ({actions[a]/total*100:5.1f}%)")

    print(f"\n── Overall Outcome ──")
    print(f"  Success: {outcomes['success']} ({outcomes['success']/total*100:.1f}%)")
    print(f"  Failure: {outcomes['failure']} ({outcomes['failure']/total*100:.1f}%)")

    # Pattern verification
    print("\n── Pattern Verification ──")

    insuf = [r for r in records if r["original_cause"] == "insufficient_funds"]
    near_payday = [r for r in insuf if 0 <= r["days_since_estimated_payday"] <= 3]
    far_payday = [r for r in insuf if r["days_since_estimated_payday"] < 0 or r["days_since_estimated_payday"] > 3]
    if near_payday and far_payday:
        sr_near = sum(1 for r in near_payday if r["outcome"] == "success") / len(near_payday)
        sr_far = sum(1 for r in far_payday if r["outcome"] == "success") / len(far_payday)
        print(f"  insufficient_funds near payday:  {sr_near:.1%} ({len(near_payday)} records)")
        print(f"  insufficient_funds far payday:   {sr_far:.1%} ({len(far_payday)} records)")

    outage = [r for r in records if r["original_cause"] == "bank_outage"]
    outage_good = [r for r in outage if r["days_since_failure"] <= 1 and 6 <= r["time_of_day"] <= 18]
    outage_bad = [r for r in outage if r not in outage_good]
    if outage_good and outage_bad:
        sr_good = sum(1 for r in outage_good if r["outcome"] == "success") / len(outage_good)
        sr_bad = sum(1 for r in outage_bad if r["outcome"] == "success") / len(outage_bad)
        print(f"  bank_outage well-timed retry:    {sr_good:.1%} ({len(outage_good)} records)")
        print(f"  bank_outage poorly-timed retry:  {sr_bad:.1%} ({len(outage_bad)} records)")

    hopeless = [r for r in records if r["original_cause"] in ("card_expired", "mandate_expired", "mandate_revoked")]
    if hopeless:
        sr_h = sum(1 for r in hopeless if r["outcome"] == "success") / len(hopeless)
        print(f"  card/mandate expired+revoked:    {sr_h:.1%} ({len(hopeless)} records)")

    a1 = [r for r in records if r["retry_attempt_number"] == 1]
    a3 = [r for r in records if r["retry_attempt_number"] == 3]
    if a1 and a3:
        sr1 = sum(1 for r in a1 if r["outcome"] == "success") / len(a1)
        sr3 = sum(1 for r in a3 if r["outcome"] == "success") / len(a3)
        print(f"  Attempt 1 success rate:          {sr1:.1%} ({len(a1)} records)")
        print(f"  Attempt 3 success rate:          {sr3:.1%} ({len(a3)} records)")

    insuf_auto = [r for r in insuf if r["action_type"] == "auto_retry"]
    insuf_sms = [r for r in insuf if r["action_type"] == "sms_then_retry"]
    if insuf_auto and insuf_sms:
        sr_auto = sum(1 for r in insuf_auto if r["outcome"] == "success") / len(insuf_auto)
        sr_sms = sum(1 for r in insuf_sms if r["outcome"] == "success") / len(insuf_sms)
        print(f"  insuf_funds auto_retry:          {sr_auto:.1%} ({len(insuf_auto)} records)")
        print(f"  insuf_funds sms_then_retry:      {sr_sms:.1%} ({len(insuf_sms)} records)")

    # Notification pattern
    insuf_notif = [r for r in insuf if r["pre_debit_notification_sent"]]
    insuf_no_notif = [r for r in insuf if not r["pre_debit_notification_sent"]]
    if insuf_notif and insuf_no_notif:
        sr_notif = sum(1 for r in insuf_notif if r["outcome"] == "success") / len(insuf_notif)
        sr_no = sum(1 for r in insuf_no_notif if r["outcome"] == "success") / len(insuf_no_notif)
        print(f"  insuf_funds notif sent:          {sr_notif:.1%} ({len(insuf_notif)} records)")
        print(f"  insuf_funds notif NOT sent:      {sr_no:.1%} ({len(insuf_no_notif)} records)")

    notif_counts = Counter(r["pre_debit_notification_sent"] for r in records)
    print(f"\n── Pre-Debit Notification ──")
    print(f"  Sent:     {notif_counts[True]:4d}  ({notif_counts[True]/total*100:.1f}%)")
    print(f"  Not sent: {notif_counts[False]:4d}  ({notif_counts[False]/total*100:.1f}%)")

    total_recovered = sum(r["amount_recovered"] for r in records)
    total_at_risk = sum(r["amount"] for r in records)
    total_cost = sum(r["action_cost"] for r in records)
    print(f"\n── Financial Summary ──")
    print(f"  Total at risk:  ₹{total_at_risk:,.2f}")
    print(f"  Gross recovered: ₹{total_recovered:,.2f}")
    print(f"  Total cost:     ₹{total_cost:,.2f}")
    print(f"  Net recovered:  ₹{total_recovered - total_cost:,.2f}")


if __name__ == "__main__":
    generate()
