"""Driver loop: pops events from the queue in chronological order and processes them."""

import logging

from simclock.sim_clock import SimClock
from simclock.event_queue import EventQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def process_event(event: dict) -> None:
    # TODO: Stage 5 — route to LangGraph action nodes
    logger.info(
        "Processed event %s | type=%s | scheduled=%s | payload=%s",
        event["id"],
        event["event_type"],
        event["scheduled_time"],
        event["payload"],
    )


def run(clock: SimClock | None = None, queue: EventQueue | None = None) -> list[dict]:
    clock = clock or SimClock()
    queue = queue or EventQueue()
    processed = []

    while True:
        event = queue.pop_next()
        if event is None:
            break
        clock.set(event["scheduled_time"])
        logger.info("Clock set to %s", clock.now())
        process_event(event)
        processed.append(event)

    logger.info("Driver loop finished — %d events processed.", len(processed))
    return processed


if __name__ == "__main__":
    run()
