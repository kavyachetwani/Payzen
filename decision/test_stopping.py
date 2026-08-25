"""Tests for stopping rules including NPCI UPI AutoPay timing compliance."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision.stopping import check_stop, clamp_to_non_peak, is_upi_peak_hour


# ── Original stopping rule tests ──

def test_three_attempt_cap_blocks():
    result = check_stop(
        cause="insufficient_funds", attempt_number=4,
        last_retry_time=None, current_time=None,
        pre_debit_notification_sent=True,
    )
    assert not result["allowed"]
    assert "exceeds max" in result["reason"]


def test_non_retryable_cause_rejected():
    for cause in ["mandate_expired", "mandate_revoked", "card_expired", "afa_stuck"]:
        result = check_stop(
            cause=cause, attempt_number=1,
            last_retry_time=None, current_time=None,
            pre_debit_notification_sent=True,
        )
        assert not result["allowed"], f"{cause} should be non-retryable"
        assert "non-retryable" in result["reason"]


def test_notification_forcing_rule():
    result = check_stop(
        cause="insufficient_funds", attempt_number=1,
        last_retry_time=None, current_time=None,
        pre_debit_notification_sent=False,
    )
    assert result["allowed"]
    assert result["force_action"] == "sms_then_retry"


def test_notification_not_forced_when_sent():
    result = check_stop(
        cause="insufficient_funds", attempt_number=1,
        last_retry_time=None, current_time=None,
        pre_debit_notification_sent=True,
    )
    assert result["allowed"]
    assert result["force_action"] is None


def test_cooldown_blocks():
    result = check_stop(
        cause="bank_outage", attempt_number=2,
        last_retry_time="2026-01-05T10:00:00",
        current_time="2026-01-05T12:00:00",
        pre_debit_notification_sent=True,
    )
    assert not result["allowed"]
    assert "cooldown" in result["reason"]


def test_cooldown_allows_after_4h():
    result = check_stop(
        cause="bank_outage", attempt_number=2,
        last_retry_time="2026-01-05T10:00:00",
        current_time="2026-01-05T14:01:00",
        pre_debit_notification_sent=True,
    )
    assert result["allowed"]


def test_ambiguous_max_1_attempt():
    result = check_stop(
        cause="ambiguous", attempt_number=2,
        last_retry_time=None, current_time=None,
        pre_debit_notification_sent=True,
    )
    assert not result["allowed"]
    assert "exceeds max 1" in result["reason"]


# ── NPCI UPI AutoPay timing compliance tests ──

def test_upi_peak_11am_clamped_to_1pm():
    """UPI AutoPay retry at 11:00 AM (peak) -> clamped to 1:00 PM."""
    h, m = clamp_to_non_peak(11, 0)
    assert (h, m) == (13, 0), f"Expected (13, 0), got ({h}, {m})"


def test_upi_peak_6pm_clamped_to_930pm():
    """UPI AutoPay retry at 6:00 PM (peak) -> clamped to 9:30 PM."""
    h, m = clamp_to_non_peak(18, 0)
    assert (h, m) == (21, 30), f"Expected (21, 30), got ({h}, {m})"


def test_upi_non_peak_8am_unchanged():
    """UPI AutoPay retry at 8:00 AM (non-peak) -> unchanged."""
    h, m = clamp_to_non_peak(8, 0)
    assert (h, m) == (8, 0), f"Expected (8, 0), got ({h}, {m})"


def test_upi_attempt1_12h_blocked():
    """UPI AutoPay attempt 1 at 12h after failure -> blocked (must be >= 24h)."""
    result = check_stop(
        cause="insufficient_funds", attempt_number=1,
        last_retry_time="2026-01-05T10:00:00",
        current_time="2026-01-05T22:00:00",
        pre_debit_notification_sent=True,
        payment_method="upi_autopay",
    )
    assert not result["allowed"]
    assert "UPI AutoPay" in result["reason"]
    assert "requires >= 24h" in result["reason"]


def test_upi_attempt2_48h_blocked():
    """UPI AutoPay attempt 2 at 48h after failure -> blocked (must be >= 72h)."""
    result = check_stop(
        cause="insufficient_funds", attempt_number=2,
        last_retry_time="2026-01-05T10:00:00",
        current_time="2026-01-07T10:00:00",
        pre_debit_notification_sent=True,
        payment_method="upi_autopay",
    )
    assert not result["allowed"]
    assert "UPI AutoPay" in result["reason"]
    assert "requires >= 72h" in result["reason"]


def test_enach_11am_allowed():
    """eNACH retry at 11:00 AM -> allowed (no peak-hour restriction)."""
    result = check_stop(
        cause="bank_outage", attempt_number=1,
        last_retry_time="2026-01-04T08:00:00",
        current_time="2026-01-05T11:00:00",
        pre_debit_notification_sent=True,
        payment_method="enach",
    )
    assert result["allowed"], f"eNACH should allow 11 AM retry, got: {result['reason']}"


def test_upi_peak_hour_detection():
    """Verify peak hour detection covers both windows."""
    assert is_upi_peak_hour(10, 0) is True
    assert is_upi_peak_hour(12, 30) is True
    assert is_upi_peak_hour(13, 0) is False
    assert is_upi_peak_hour(17, 0) is True
    assert is_upi_peak_hour(21, 0) is True
    assert is_upi_peak_hour(21, 30) is False
    assert is_upi_peak_hour(8, 0) is False
    assert is_upi_peak_hour(22, 0) is False


# ── Capacity constraint tests ──

from datetime import datetime
from decision.constraints import (
    clamp_call_to_rbi_hours, clamp_upi_call, ConstraintTracker,
)


def test_call_9pm_clamped_to_next_8am():
    """Call at 9:00 PM -> clamped to next 8:00 AM."""
    dt = datetime(2026, 1, 15, 21, 0, 0)
    result = clamp_call_to_rbi_hours(dt)
    assert result == datetime(2026, 1, 16, 8, 0, 0), f"Got {result}"


def test_call_3pm_unchanged():
    """Call at 3:00 PM -> unchanged (within 8AM-7PM)."""
    dt = datetime(2026, 1, 15, 15, 0, 0)
    result = clamp_call_to_rbi_hours(dt)
    assert result == dt, f"Got {result}"


def test_upi_call_2pm_unchanged():
    """UPI AutoPay + call at 2:00 PM -> unchanged (in NPCI non-peak AND RBI window)."""
    dt = datetime(2026, 1, 15, 14, 0, 0)
    result = clamp_upi_call(dt)
    assert result == dt, f"Got {result}"


def test_upi_call_11am_clamped():
    """UPI AutoPay + call at 11:00 AM -> clamped to 1PM (NPCI peak)."""
    dt = datetime(2026, 1, 15, 11, 0, 0)
    result = clamp_upi_call(dt)
    assert result == datetime(2026, 1, 15, 13, 0, 0), f"Got {result}"


def test_daily_call_budget_30():
    """Day with 35 call-eligible -> top 30 by amount get calls, bottom 5 downgraded."""
    tracker = ConstraintTracker()
    day = datetime(2026, 1, 15)

    pending = []
    for i in range(35):
        pending.append({
            "payment_id": f"P_{i:03d}",
            "customer_id": f"C_{i:03d}",
            "amount": (35 - i) * 1000.0,
            "action": "call_then_retry",
            "scheduled_time": day.isoformat(),
        })

    result = tracker.prioritize_calls(pending, day)
    calls = [p for p in result if p["action"] == "call_then_retry"]
    downgrades = [p for p in result if p.get("downgraded")]
    assert len(calls) == 30, f"Expected 30 calls, got {len(calls)}"
    assert len(downgrades) == 5, f"Expected 5 downgrades, got {len(downgrades)}"

    downgraded_amounts = sorted([p["amount"] for p in downgrades])
    assert downgraded_amounts == [1000.0, 2000.0, 3000.0, 4000.0, 5000.0], \
        f"Wrong payments downgraded: {downgraded_amounts}"


def test_customer_already_called_once():
    """Customer already called once this cycle -> second call downgraded to SMS."""
    tracker = ConstraintTracker()
    t1 = datetime(2026, 1, 15, 10, 0, 0)
    t2 = datetime(2026, 1, 16, 10, 0, 0)

    r1 = tracker.apply_constraints("call_then_retry", "C_001", t1, "P_001")
    assert r1["action"] == "call_then_retry"
    assert not r1["downgraded"]

    r2 = tracker.apply_constraints("call_then_retry", "C_001", t2, "P_002")
    assert r2["action"] == "sms_then_retry"
    assert r2["downgraded"]
    assert "already called" in r2["reason"]


def test_customer_3_sms_fourth_downgraded():
    """Customer already received 3 SMS -> fourth downgraded to auto_retry."""
    tracker = ConstraintTracker()
    base = datetime(2026, 1, 15, 10, 0, 0)

    for i in range(3):
        t = datetime(2026, 1, 15 + i, 10, 0, 0)
        r = tracker.apply_constraints("sms_then_retry", "C_002", t, f"P_{i}")
        assert r["action"] == "sms_then_retry"

    t4 = datetime(2026, 1, 18, 10, 0, 0)
    r4 = tracker.apply_constraints("sms_then_retry", "C_002", t4, "P_003")
    assert r4["action"] == "auto_retry"
    assert r4["downgraded"]
    assert "3 SMS" in r4["reason"]


def test_audit_log_records_downgrades():
    """Verify audit log records original recommendation + actual action + reason."""
    tracker = ConstraintTracker()
    t1 = datetime(2026, 1, 15, 10, 0, 0)
    t2 = datetime(2026, 1, 16, 10, 0, 0)

    tracker.apply_constraints("call_then_retry", "C_001", t1, "P_001")
    tracker.apply_constraints("call_then_retry", "C_001", t2, "P_002")

    assert len(tracker.audit_log) == 1
    entry = tracker.audit_log[0]
    assert entry["payment_id"] == "P_002"
    assert entry["recommended_action"] == "call_then_retry"
    assert entry["actual_action"] == "sms_then_retry"
    assert "already called" in entry["reason"]


if __name__ == "__main__":
    test_three_attempt_cap_blocks()
    test_non_retryable_cause_rejected()
    test_notification_forcing_rule()
    test_notification_not_forced_when_sent()
    test_cooldown_blocks()
    test_cooldown_allows_after_4h()
    test_ambiguous_max_1_attempt()
    test_upi_peak_11am_clamped_to_1pm()
    test_upi_peak_6pm_clamped_to_930pm()
    test_upi_non_peak_8am_unchanged()
    test_upi_attempt1_12h_blocked()
    test_upi_attempt2_48h_blocked()
    test_enach_11am_allowed()
    test_upi_peak_hour_detection()
    test_call_9pm_clamped_to_next_8am()
    test_call_3pm_unchanged()
    test_upi_call_2pm_unchanged()
    test_upi_call_11am_clamped()
    test_daily_call_budget_30()
    test_customer_already_called_once()
    test_customer_3_sms_fourth_downgraded()
    test_audit_log_records_downgrades()
    print("All 22 tests passed.")
