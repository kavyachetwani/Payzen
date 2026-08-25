"""Tests for stopping rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision.stopping import check_stop


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


if __name__ == "__main__":
    test_three_attempt_cap_blocks()
    test_non_retryable_cause_rejected()
    test_notification_forcing_rule()
    test_notification_not_forced_when_sent()
    test_cooldown_blocks()
    test_cooldown_allows_after_4h()
    test_ambiguous_max_1_attempt()
    print("All 7 stopping rule tests passed.")
