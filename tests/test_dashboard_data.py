"""Test Suite 5: Dashboard data integrity — summaries have all required fields."""

import math
from collections import Counter


REQUIRED_FIELDS = [
    "payment_id", "customer_id", "amount", "diagnosed_cause",
    "final_outcome", "total_amount_recovered", "total_action_cost",
    "net_recovered",
]


def test_all_required_fields_present(summaries):
    for s in summaries:
        for field in REQUIRED_FIELDS:
            assert field in s, f"{s.get('payment_id', '?')}: missing field '{field}'"


def test_no_null_required_fields(summaries):
    for s in summaries:
        for field in ["payment_id", "amount", "diagnosed_cause", "final_outcome"]:
            assert s.get(field) is not None, f"{s.get('payment_id', '?')}: {field} is null"


def test_no_nan_amounts(summaries):
    for s in summaries:
        for field in ["amount", "total_amount_recovered", "total_action_cost", "net_recovered"]:
            val = s.get(field, 0)
            if isinstance(val, float):
                assert not math.isnan(val), f"{s['payment_id']}: {field} is NaN"
                assert not math.isinf(val), f"{s['payment_id']}: {field} is Infinity"


def test_no_negative_amounts(summaries):
    for s in summaries:
        assert s["amount"] >= 0, f"{s['payment_id']}: negative amount"
        assert s.get("total_action_cost", 0) >= 0, f"{s['payment_id']}: negative action cost"
        assert s.get("total_amount_recovered", 0) >= 0, f"{s['payment_id']}: negative recovered"


def test_outcome_counts_add_up(summaries, events):
    outcomes = Counter(s["final_outcome"] for s in summaries)
    total = sum(outcomes.values())
    tier3_pending = sum(1 for e in events if e.get("tier") == 3 and e.get("action_type") == "awaiting_decision")
    expected = 500 - tier3_pending
    assert total == expected, f"Outcome total {total} != {expected} (500 - {tier3_pending} T3 pending). Distribution: {dict(outcomes)}"


def test_known_outcomes_only(summaries):
    known = {
        "recovered", "failed_exhausted", "escalated", "gate_blocked",
        "card_update_sent", "mandate_resequenced", "merchant_rejected",
    }
    for s in summaries:
        outcome = s["final_outcome"]
        assert outcome in known, f"{s['payment_id']}: unknown outcome '{outcome}'"
