"""Wire bandit decisions into the SimClock event queue.

Enforces NPCI UPI AutoPay timing constraints: non-peak execution windows
and per-attempt minimum spacing (24h/72h/7d).
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simclock.sim_clock import SimClock
from decision.stopping import clamp_to_non_peak, UPI_ATTEMPT_MIN_HOURS


def _clamp_upi_time(dt: datetime) -> datetime:
    """Clamp a datetime into the nearest UPI non-peak window."""
    h, m = clamp_to_non_peak(dt.hour, dt.minute)
    if (h, m) == (dt.hour, dt.minute):
        return dt
    clamped = dt.replace(hour=h, minute=m, second=0, microsecond=0)
    if clamped < dt:
        clamped += timedelta(days=1)
    return clamped


def _enforce_upi_spacing(scheduled: datetime, failure_time: datetime,
                         attempt_number: int) -> datetime:
    """Ensure minimum spacing from failure time for UPI AutoPay."""
    min_hours = UPI_ATTEMPT_MIN_HOURS.get(attempt_number, 24)
    earliest = failure_time + timedelta(hours=min_hours)
    if scheduled < earliest:
        scheduled = earliest
    return scheduled


def schedule_retry(clock: SimClock, event_queue,
                   diagnosis_result: dict, bandit_decision: str,
                   attempt_number: int, action_cost: float,
                   delay_hours: float = 6.0,
                   payment_method: str = "enach",
                   failure_time: datetime | None = None) -> dict:
    """Create a scheduled retry event in the SimClock event queue."""
    scheduled_time = clock.now() + timedelta(hours=delay_hours)

    if payment_method == "upi_autopay":
        if failure_time is not None:
            scheduled_time = _enforce_upi_spacing(
                scheduled_time, failure_time, attempt_number
            )
        scheduled_time = _clamp_upi_time(scheduled_time)
    else:
        pass

    event = {
        "event_type": "retry_attempt",
        "scheduled_time": scheduled_time.isoformat(),
        "payload": {
            "payment_id": diagnosis_result["payment_id"],
            "cause": diagnosis_result["diagnosed_cause"],
            "action_type": bandit_decision,
            "attempt_number": attempt_number,
            "action_cost": action_cost,
            "payment_method": payment_method,
        },
    }

    if event_queue is not None:
        event_queue.enqueue(event)

    return event
