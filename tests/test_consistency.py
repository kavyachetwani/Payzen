"""Test Suite 1A: Pipeline consistency — all numbers must be internally consistent."""

from collections import Counter


def test_outcome_sum_equals_500(summaries):
    outcomes = Counter(s["final_outcome"] for s in summaries)
    total = sum(outcomes.values())
    assert total == 500, f"Expected 500 summaries, got {total}. Outcomes: {dict(outcomes)}"


def test_no_duplicate_payment_ids_in_summary(summaries):
    pids = [s["payment_id"] for s in summaries]
    assert len(pids) == len(set(pids)), f"Duplicate payment_ids: {len(pids)} total, {len(set(pids))} unique"


def test_every_summary_has_events(summaries, events):
    event_pids = set(e["payment_id"] for e in events)
    for s in summaries:
        assert s["payment_id"] in event_pids, f"Summary {s['payment_id']} has no events"


def test_no_orphaned_events(summaries, events):
    summary_pids = set(s["payment_id"] for s in summaries)
    for e in events:
        assert e["payment_id"] in summary_pids, f"Orphaned event for {e['payment_id']}"


def test_summary_count_equals_records(summaries, records):
    assert len(summaries) == len(records), f"Summaries: {len(summaries)}, Records: {len(records)}"


def test_total_at_risk_consistent(summaries, records):
    records_total = sum(r["amount"] for r in records)
    summary_total = sum(s["amount"] for s in summaries)
    assert abs(records_total - summary_total) < 0.01


def test_net_recovered_consistent(summaries):
    total_recovered = sum(s.get("total_amount_recovered", 0) for s in summaries)
    total_cost = sum(s.get("total_action_cost", 0) for s in summaries)
    total_net = sum(s.get("net_recovered", 0) for s in summaries)
    assert abs(total_net - (total_recovered - total_cost)) < 1.0


def test_event_count_reasonable(events):
    n_initial = sum(1 for e in events if e["event_type"] == "initial_processing")
    n_retry = sum(1 for e in events if e["event_type"] in ("retry_attempt", "escalation_after_exhaustion"))
    assert n_initial == 500, f"Expected 500 initial events, got {n_initial}"
    assert n_retry <= 1500, f"Retry events {n_retry} exceeds upper bound 1500"
