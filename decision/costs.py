"""Per-action cost table for retry decisions."""

ACTION_COSTS = {
    "auto_retry": 0.0,
    "sms_then_retry": 2.0,
    "call_then_retry": 15.0,
}

ARMS = list(ACTION_COSTS.keys())
