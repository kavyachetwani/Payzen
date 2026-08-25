"""Retryable vs non-retryable cause mapping."""

RETRYABLE = {
    "insufficient_funds": {"retryable": True, "max_attempts": 3},
    "bank_outage": {"retryable": True, "max_attempts": 3},
    "afa_stuck": {"retryable": False, "route_to": "customer_auth_action"},
    "mandate_expired": {"retryable": False, "route_to": "mandate_resequence"},
    "mandate_revoked": {"retryable": False, "route_to": "escalation_conversation"},
    "card_expired": {"retryable": False, "route_to": "card_update_link"},
    "ambiguous": {"retryable": True, "max_attempts": 1},
}


def is_retryable(cause: str) -> bool:
    return RETRYABLE.get(cause, {}).get("retryable", False)


def max_attempts(cause: str) -> int:
    entry = RETRYABLE.get(cause, {})
    if not entry.get("retryable", False):
        return 0
    return entry.get("max_attempts", 3)


def route_action(cause: str) -> str | None:
    entry = RETRYABLE.get(cause, {})
    if entry.get("retryable", False):
        return None
    return entry.get("route_to")
