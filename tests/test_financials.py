"""Test Suite 1B: Financial math verification."""

import math


def test_net_equals_recovered_minus_cost(summaries):
    for s in summaries:
        expected_net = s.get("total_amount_recovered", 0) - s.get("total_action_cost", 0)
        actual_net = s.get("net_recovered", 0)
        assert abs(expected_net - actual_net) < 0.01, \
            f"{s['payment_id']}: expected net {expected_net}, got {actual_net}"


def test_action_cost_matches_event_sum(summaries, events):
    events_by_pid = {}
    for e in events:
        pid = e["payment_id"]
        if pid not in events_by_pid:
            events_by_pid[pid] = []
        events_by_pid[pid].append(e)

    for s in summaries:
        pid = s["payment_id"]
        if s.get("total_attempts", 0) == 0:
            continue
        evts = events_by_pid.get(pid, [])
        event_cost = sum(e.get("action_cost", 0) for e in evts)
        summary_cost = s.get("total_action_cost", 0)
        assert abs(event_cost - summary_cost) < 0.01, \
            f"{pid}: event cost sum {event_cost} != summary cost {summary_cost}"


def test_recovered_payments_get_full_amount(summaries):
    for s in summaries:
        if s.get("final_outcome") == "recovered":
            assert s.get("total_amount_recovered", 0) == s["amount"], \
                f"{s['payment_id']}: recovered {s.get('total_amount_recovered')} != amount {s['amount']}"


def test_non_recovered_get_zero(summaries):
    for s in summaries:
        if s.get("final_outcome") not in ("recovered",):
            assert s.get("total_amount_recovered", 0) == 0, \
                f"{s['payment_id']}: outcome={s.get('final_outcome')} but recovered {s.get('total_amount_recovered')}"


def test_headline_net_matches_sum(summaries):
    total_net = sum(s.get("net_recovered", 0) for s in summaries)
    total_recovered = sum(s.get("total_amount_recovered", 0) for s in summaries)
    total_cost = sum(s.get("total_action_cost", 0) for s in summaries)
    assert abs(total_net - (total_recovered - total_cost)) < 1.0


def test_no_negative_amounts(summaries):
    for s in summaries:
        assert s["amount"] >= 0, f"{s['payment_id']}: negative amount {s['amount']}"
        assert s.get("total_action_cost", 0) >= 0, f"{s['payment_id']}: negative action cost"
        assert s.get("total_amount_recovered", 0) >= 0, f"{s['payment_id']}: negative recovered"


def test_no_recovery_exceeds_amount(summaries):
    for s in summaries:
        assert s.get("total_amount_recovered", 0) <= s["amount"] + 0.01, \
            f"{s['payment_id']}: recovered {s.get('total_amount_recovered')} > amount {s['amount']}"


def test_no_nan_or_infinity(summaries):
    for s in summaries:
        for key in ("amount", "total_amount_recovered", "total_action_cost", "net_recovered"):
            val = s.get(key, 0)
            assert not math.isnan(val), f"{s['payment_id']}: {key} is NaN"
            assert not math.isinf(val), f"{s['payment_id']}: {key} is Infinity"
