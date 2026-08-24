from datetime import datetime, timedelta

DEFAULT_ANCHOR = datetime(2026, 1, 1)


class SimClock:
    def __init__(self, anchor: datetime | None = None):
        self._current = anchor or DEFAULT_ANCHOR

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current += delta

    def set(self, timestamp: datetime) -> None:
        self._current = timestamp
