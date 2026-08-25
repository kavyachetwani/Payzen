"""Hard stopping rules that override the bandit.

Includes NPCI UPI AutoPay-specific retry timing constraints
(Aug 2025 circular on non-peak execution windows).
"""

from decision.policy import is_retryable, max_attempts

UPI_PEAK_WINDOWS = [
    (10, 0, 13, 0),
    (17, 0, 21, 30),
]

UPI_ATTEMPT_MIN_HOURS = {1: 24, 2: 72, 3: 168}


def _minutes_of_day(hour: int, minute: int) -> int:
    return hour * 60 + minute


def is_upi_peak_hour(hour: int, minute: int = 0) -> bool:
    t = _minutes_of_day(hour, minute)
    for sh, sm, eh, em in UPI_PEAK_WINDOWS:
        if _minutes_of_day(sh, sm) <= t < _minutes_of_day(eh, em):
            return True
    return False


def clamp_to_non_peak(hour: int, minute: int = 0) -> tuple[int, int]:
    """Clamp a time into the nearest UPI non-peak window.
    Returns (hour, minute) of the next allowed slot.
    """
    t = _minutes_of_day(hour, minute)

    if _minutes_of_day(10, 0) <= t < _minutes_of_day(13, 0):
        return (13, 0)
    if _minutes_of_day(17, 0) <= t < _minutes_of_day(21, 30):
        return (21, 30)

    return (hour, minute)


def check_stop(cause: str, attempt_number: int,
               last_retry_time: str | None, current_time: str | None,
               pre_debit_notification_sent: bool,
               payment_method: str = "enach") -> dict:
    """Check all stopping rules. Returns {allowed, reason, force_action}."""

    if not is_retryable(cause):
        return {
            "allowed": False,
            "reason": f"non-retryable cause: {cause}",
            "force_action": None,
        }

    cap = max_attempts(cause)
    if attempt_number > cap:
        return {
            "allowed": False,
            "reason": f"attempt {attempt_number} exceeds max {cap} for {cause}",
            "force_action": None,
        }

    if last_retry_time and current_time:
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S"
        try:
            last = datetime.strptime(last_retry_time[:19], fmt)
            curr = datetime.strptime(current_time[:19], fmt)
            hours_diff = (curr - last).total_seconds() / 3600

            if payment_method == "upi_autopay":
                min_hours = UPI_ATTEMPT_MIN_HOURS.get(attempt_number, 24)
                if hours_diff < min_hours:
                    return {
                        "allowed": False,
                        "reason": f"UPI AutoPay: {hours_diff:.1f}h since last retry, "
                                  f"attempt {attempt_number} requires >= {min_hours}h",
                        "force_action": None,
                    }
            else:
                if hours_diff < 4.0:
                    return {
                        "allowed": False,
                        "reason": f"cooldown: only {hours_diff:.1f}h since last retry (min 4h)",
                        "force_action": None,
                    }
        except ValueError:
            pass

    if payment_method == "upi_autopay" and current_time:
        try:
            from datetime import datetime
            t = datetime.strptime(current_time[:19], "%Y-%m-%dT%H:%M:%S")
            if is_upi_peak_hour(t.hour, t.minute):
                return {
                    "allowed": False,
                    "reason": f"UPI AutoPay: {t.hour:02d}:{t.minute:02d} is peak hour, "
                              f"retry blocked until non-peak window",
                    "force_action": None,
                }
        except ValueError:
            pass

    force_action = None
    if not pre_debit_notification_sent and cause == "insufficient_funds" and attempt_number == 1:
        force_action = "sms_then_retry"

    return {
        "allowed": True,
        "reason": "ok",
        "force_action": force_action,
    }
