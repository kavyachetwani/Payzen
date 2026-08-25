"""Capacity and regulatory constraints that sit on top of the bandit.

The bandit recommends the ideal action; this layer applies operational reality.
The audit log records both the recommendation and the actual action with
downgrade reason.

Constraints (in application order):
1. RBI contact hours for calls: 8AM-7PM only (regulatory)
2. Daily call budget: max 30 per simulated day (operational)
3. Amount-based priority when budget binds (operational)
4. Per-customer contact limits per 30-day cycle (operational)
"""

from collections import defaultdict
from datetime import datetime, timedelta

RBI_CALL_START_HOUR = 8
RBI_CALL_END_HOUR = 19

DAILY_CALL_BUDGET = 30

CUSTOMER_MAX_CALLS_PER_CYCLE = 1
CUSTOMER_MAX_SMS_PER_CYCLE = 3
CYCLE_DAYS = 30


class ConstraintTracker:
    """Tracks per-day call budgets and per-customer contact counts."""

    def __init__(self):
        self.calls_per_day: dict[str, int] = defaultdict(int)
        self.customer_calls: dict[str, list[str]] = defaultdict(list)
        self.customer_sms: dict[str, list[str]] = defaultdict(list)
        self.audit_log: list[dict] = []

    def _day_key(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d")

    def _contacts_in_window(self, timestamps: list[str],
                            current: datetime) -> int:
        cutoff = current - timedelta(days=CYCLE_DAYS)
        return sum(1 for ts in timestamps
                   if datetime.fromisoformat(ts) >= cutoff)

    def remaining_call_budget(self, day: datetime) -> int:
        used = self.calls_per_day[self._day_key(day)]
        return max(0, DAILY_CALL_BUDGET - used)

    def apply_constraints(self, action: str, customer_id: str,
                          scheduled_time: datetime,
                          payment_id: str = "") -> dict:
        """Apply all constraints to a bandit recommendation.

        Returns {action, downgraded, original_action, reason}.
        """
        original = action
        reason = None

        if action == "call_then_retry":
            calls_in_cycle = self._contacts_in_window(
                self.customer_calls[customer_id], scheduled_time
            )
            if calls_in_cycle >= CUSTOMER_MAX_CALLS_PER_CYCLE:
                action = "sms_then_retry"
                reason = f"customer {customer_id} already called {calls_in_cycle}x this cycle (max {CUSTOMER_MAX_CALLS_PER_CYCLE})"

        if action == "call_then_retry":
            day_key = self._day_key(scheduled_time)
            if self.calls_per_day[day_key] >= DAILY_CALL_BUDGET:
                action = "sms_then_retry"
                reason = "daily call budget exhausted"

        if action == "sms_then_retry":
            sms_in_cycle = self._contacts_in_window(
                self.customer_sms[customer_id], scheduled_time
            )
            if sms_in_cycle >= CUSTOMER_MAX_SMS_PER_CYCLE:
                action = "auto_retry"
                reason = f"customer {customer_id} already received {sms_in_cycle} SMS this cycle (max {CUSTOMER_MAX_SMS_PER_CYCLE})"

        if action == "call_then_retry":
            self.calls_per_day[self._day_key(scheduled_time)] += 1
            self.customer_calls[customer_id].append(scheduled_time.isoformat())
        elif action == "sms_then_retry":
            self.customer_sms[customer_id].append(scheduled_time.isoformat())

        result = {
            "action": action,
            "downgraded": action != original,
            "original_action": original,
            "reason": reason,
        }

        if action != original:
            self.audit_log.append({
                "payment_id": payment_id,
                "customer_id": customer_id,
                "scheduled_time": scheduled_time.isoformat(),
                "recommended_action": original,
                "actual_action": action,
                "reason": reason,
            })

        return result

    def prioritize_calls(self, pending: list[dict],
                         day: datetime) -> list[dict]:
        """Sort call-eligible payments by amount descending, assign calls
        to top N within daily budget, downgrade the rest to sms_then_retry.

        Each item in pending: {payment_id, customer_id, amount, action,
        scheduled_time, ...}. Returns the same list with actions updated.
        """
        call_items = [p for p in pending if p["action"] == "call_then_retry"]
        non_call = [p for p in pending if p["action"] != "call_then_retry"]

        call_items.sort(key=lambda p: p["amount"], reverse=True)

        budget = self.remaining_call_budget(day)
        results = list(non_call)

        for i, item in enumerate(call_items):
            if i < budget:
                results.append(item)
            else:
                downgraded = dict(item)
                downgraded["action"] = "sms_then_retry"
                downgraded["downgraded"] = True
                downgraded["original_action"] = "call_then_retry"
                downgraded["reason"] = "lower priority — higher-value payments filled call budget"
                self.audit_log.append({
                    "payment_id": item.get("payment_id", ""),
                    "customer_id": item.get("customer_id", ""),
                    "scheduled_time": item.get("scheduled_time", day.isoformat()),
                    "recommended_action": "call_then_retry",
                    "actual_action": "sms_then_retry",
                    "reason": downgraded["reason"],
                })
                results.append(downgraded)

        return results


def clamp_call_to_rbi_hours(dt: datetime) -> datetime:
    """Clamp a call_then_retry time to RBI contact hours (8AM-7PM).
    If outside, push to next 8AM.
    """
    if RBI_CALL_START_HOUR <= dt.hour < RBI_CALL_END_HOUR:
        return dt
    if dt.hour >= RBI_CALL_END_HOUR:
        next_day = dt + timedelta(days=1)
        return next_day.replace(hour=RBI_CALL_START_HOUR, minute=0,
                                second=0, microsecond=0)
    return dt.replace(hour=RBI_CALL_START_HOUR, minute=0,
                      second=0, microsecond=0)


def clamp_upi_call(dt: datetime) -> datetime:
    """For UPI AutoPay + call_then_retry: must satisfy BOTH NPCI non-peak
    AND RBI 8AM-7PM. Valid intersection: 8AM-10AM and 1PM-5PM.
    """
    h, m = dt.hour, dt.minute
    t = h * 60 + m

    if 8 * 60 <= t < 10 * 60:
        return dt
    if 13 * 60 <= t < 17 * 60:
        return dt

    if t < 8 * 60:
        return dt.replace(hour=8, minute=0, second=0, microsecond=0)
    if 10 * 60 <= t < 13 * 60:
        return dt.replace(hour=13, minute=0, second=0, microsecond=0)
    if 17 * 60 <= t:
        next_day = dt + timedelta(days=1)
        return next_day.replace(hour=8, minute=0, second=0, microsecond=0)

    return dt
