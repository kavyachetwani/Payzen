"""Test Suite 3: Stopping rules stress tests."""

from collections import Counter, defaultdict
from datetime import datetime

import pytest


class TestNoInfiniteRetries:
    def test_no_payment_exceeds_3_retries(self, events):
        retry_counts = Counter()
        for e in events:
            if e["event_type"] in ("retry_attempt", "escalation_after_exhaustion"):
                retry_counts[e["payment_id"]] += 1
        for pid, count in retry_counts.items():
            assert count <= 3, f"{pid}: {count} retry events exceeds max 3"

    def test_ambiguous_max_1_retry(self, summaries):
        for s in summaries:
            if s.get("diagnosed_cause") == "ambiguous" and s.get("is_retryable"):
                assert s.get("total_attempts", 0) <= 1, \
                    f"{s['payment_id']}: ambiguous cause has {s.get('total_attempts')} attempts (max 1)"

    def test_total_retry_events_bounded(self, events):
        retry_count = sum(1 for e in events
                          if e["event_type"] in ("retry_attempt", "escalation_after_exhaustion"))
        assert retry_count <= 1500, f"Total retry events {retry_count} exceeds upper bound 1500"

    def test_no_attempt_number_exceeds_3(self, events):
        for e in events:
            if e["event_type"] in ("retry_attempt", "escalation_after_exhaustion"):
                assert e.get("attempt_number", 0) <= 3, \
                    f"{e['payment_id']}: attempt_number {e.get('attempt_number')} exceeds 3"


class TestNoOverContact:
    def test_max_1_call_per_customer(self, events):
        customer_calls = defaultdict(int)
        for e in events:
            if e.get("action_type") == "call_then_retry" and \
               e.get("event_type") != "initial_processing":
                cust = e.get("customer_id", "")
                customer_calls[cust] += 1
        for cust, count in customer_calls.items():
            assert count <= 1, f"Customer {cust}: {count} calls (max 1)"

    def test_max_3_sms_per_customer(self, events):
        customer_sms = defaultdict(int)
        for e in events:
            if e.get("action_type") == "sms_then_retry" and \
               e.get("event_type") != "initial_processing":
                cust = e.get("customer_id", "")
                customer_sms[cust] += 1
        for cust, count in customer_sms.items():
            assert count <= 3, f"Customer {cust}: {count} SMS (max 3)"

    def test_dnd_customers_no_contact(self, events):
        from action.compliance import get_dnd_set
        dnd = get_dnd_set()
        for e in events:
            if e.get("event_type") == "initial_processing":
                continue
            cust = e.get("customer_id", "")
            action = e.get("action_type", "")
            if cust in dnd and action in ("call_then_retry", "sms_then_retry"):
                pytest.fail(f"DND customer {cust} received contact action: {action}")

    def test_calls_within_rbi_hours(self, events):
        for e in events:
            if e.get("action_type") != "call_then_retry":
                continue
            if e.get("event_type") == "initial_processing":
                continue
            ts = e.get("sim_timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    assert 8 <= dt.hour < 19, \
                        f"{e['payment_id']}: call at {dt.hour}:00 outside RBI hours"
                except ValueError:
                    pass


class TestNoNPCIViolations:
    def test_upi_no_peak_hours(self, events, record_map):
        from decision.stopping import is_upi_peak_hour
        for e in events:
            if e.get("event_type") == "initial_processing":
                continue
            pid = e["payment_id"]
            record = record_map.get(pid, {})
            if record.get("payment_method") != "upi_autopay":
                continue
            ts = e.get("sim_timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    assert not is_upi_peak_hour(dt.hour, dt.minute), \
                        f"{pid}: UPI retry at {dt.hour}:{dt.minute:02d} is peak hour"
                except ValueError:
                    pass

    def test_upi_attempt_2_72h_gap(self, summaries):
        for s in summaries:
            if s.get("payment_method") != "upi_autopay":
                continue
            history = s.get("attempt_history", [])
            failure_time = s.get("failure_timestamp", "")
            if not failure_time or len(history) < 2:
                continue
            try:
                ft = datetime.fromisoformat(failure_time)
                for a in history:
                    if a.get("attempt", 0) == 2 and a.get("time"):
                        at = datetime.fromisoformat(a["time"])
                        hours = (at - ft).total_seconds() / 3600
                        assert hours >= 72, \
                            f"{s['payment_id']}: UPI attempt 2 at {hours:.1f}h (min 72h)"
            except ValueError:
                pass

    def test_upi_attempt_3_168h_gap(self, summaries):
        for s in summaries:
            if s.get("payment_method") != "upi_autopay":
                continue
            history = s.get("attempt_history", [])
            failure_time = s.get("failure_timestamp", "")
            if not failure_time or len(history) < 3:
                continue
            try:
                ft = datetime.fromisoformat(failure_time)
                for a in history:
                    if a.get("attempt", 0) == 3 and a.get("time"):
                        at = datetime.fromisoformat(a["time"])
                        hours = (at - ft).total_seconds() / 3600
                        assert hours >= 168, \
                            f"{s['payment_id']}: UPI attempt 3 at {hours:.1f}h (min 168h)"
            except ValueError:
                pass


class TestNoNegativeRecoveryMath:
    def test_no_excess_loss(self, summaries):
        for s in summaries:
            net = s.get("net_recovered", 0)
            cost = s.get("total_action_cost", 0)
            assert net >= -cost - 0.01, f"{s['payment_id']}: net {net} < -(cost {cost})"

    def test_no_over_recovery(self, summaries):
        for s in summaries:
            recovered = s.get("total_amount_recovered", 0)
            assert recovered <= s["amount"] + 0.01, \
                f"{s['payment_id']}: recovered {recovered} > amount {s['amount']}"

    def test_no_negative_action_cost(self, summaries):
        for s in summaries:
            assert s.get("total_action_cost", 0) >= 0, \
                f"{s['payment_id']}: negative action cost"
