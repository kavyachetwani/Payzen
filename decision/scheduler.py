"""Wire bandit decisions into the SimClock event queue."""

import sys
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simclock.sim_clock import SimClock


def schedule_retry(clock: SimClock, event_queue,
                   diagnosis_result: dict, bandit_decision: str,
                   attempt_number: int, action_cost: float,
                   delay_hours: float = 6.0) -> dict:
    """Create a scheduled retry event in the SimClock event queue.

    Returns the event dict (not yet enqueued if event_queue is None).
    """
    scheduled_time = clock.now() + timedelta(hours=delay_hours)

    event = {
        "event_type": "retry_attempt",
        "scheduled_time": scheduled_time.isoformat(),
        "payload": {
            "payment_id": diagnosis_result["payment_id"],
            "cause": diagnosis_result["diagnosed_cause"],
            "action_type": bandit_decision,
            "attempt_number": attempt_number,
            "action_cost": action_cost,
        },
    }

    if event_queue is not None:
        event_queue.enqueue(event)

    return event
