"""Hard stopping rules that override the bandit."""

from decision.policy import is_retryable, max_attempts


def check_stop(cause: str, attempt_number: int,
               last_retry_time: str | None, current_time: str | None,
               pre_debit_notification_sent: bool) -> dict:
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
            if hours_diff < 4.0:
                return {
                    "allowed": False,
                    "reason": f"cooldown: only {hours_diff:.1f}h since last retry (min 4h)",
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
