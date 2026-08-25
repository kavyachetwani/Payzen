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
    print("All 14 tests passed.")
