"""Tests for SimClock, EventQueue, and the driver loop.

Uses an in-memory fake Firestore client so tests run without credentials.
"""

from datetime import datetime, timedelta

import pytest

from simclock.sim_clock import SimClock, DEFAULT_ANCHOR
from simclock.event_queue import EventQueue
from simclock.driver import run


# ---------------------------------------------------------------------------
# In-memory Firestore fake
# ---------------------------------------------------------------------------

class FakeDocRef:
    def __init__(self, store: dict, doc_id: str):
        self._store = store
        self._id = doc_id

    def set(self, data: dict):
        self._store[self._id] = dict(data)

    def update(self, fields: dict):
        self._store[self._id].update(fields)

    @property
    def reference(self):
        return self


class FakeQuery:
    def __init__(self, docs: list[dict], store: dict):
        self._docs = docs
        self._store = store

    def where(self, field, op, value):
        filtered = [d for d in self._docs if d.get(field) == value]
        return FakeQuery(filtered, self._store)

    def order_by(self, field):
        self._docs.sort(key=lambda d: d[field])
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def stream(self):
        for d in self._docs:
            yield FakeDocRef(self._store, d["id"])

    def to_dict(self):
        return self._docs[0] if self._docs else None


class FakeDocSnapshot:
    def __init__(self, store, doc_id):
        self._store = store
        self._id = doc_id
        self.reference = FakeDocRef(store, doc_id)

    def to_dict(self):
        return dict(self._store[self._id])


class FakeCollection:
    def __init__(self, store: dict):
        self._store = store

    def document(self, doc_id: str):
        return FakeDocRef(self._store, doc_id)

    def where(self, field, op, value):
        docs = [v for v in self._store.values() if v.get(field) == value]
        return _FakeChainQuery(docs, self._store)


class _FakeChainQuery:
    def __init__(self, docs, store):
        self._docs = list(docs)
        self._store = store

    def where(self, field, op, value):
        self._docs = [d for d in self._docs if d.get(field) == value]
        return self

    def order_by(self, field):
        self._docs.sort(key=lambda d: d[field])
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def stream(self):
        for d in self._docs:
            yield FakeDocSnapshot(self._store, d["id"])


class FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, dict] = {}

    def collection(self, name: str):
        if name not in self._collections:
            self._collections[name] = {}
        return FakeCollection(self._collections[name])


# ---------------------------------------------------------------------------
# SimClock unit tests
# ---------------------------------------------------------------------------

class TestSimClock:
    def test_default_anchor(self):
        clock = SimClock()
        assert clock.now() == DEFAULT_ANCHOR

    def test_custom_anchor(self):
        ts = datetime(2025, 6, 15, 12, 0, 0)
        clock = SimClock(anchor=ts)
        assert clock.now() == ts

    def test_advance(self):
        clock = SimClock()
        clock.advance(timedelta(hours=3, minutes=30))
        assert clock.now() == DEFAULT_ANCHOR + timedelta(hours=3, minutes=30)

    def test_set(self):
        clock = SimClock()
        target = datetime(2026, 7, 4, 18, 0, 0)
        clock.set(target)
        assert clock.now() == target


# ---------------------------------------------------------------------------
# EventQueue unit tests
# ---------------------------------------------------------------------------

class TestEventQueue:
    def test_enqueue_and_pop(self):
        db = FakeFirestoreClient()
        q = EventQueue(db=db)
        t = datetime(2026, 1, 1, 10, 0, 0)
        event_id = q.enqueue("test", t, {"key": "val"})
        assert isinstance(event_id, str)

        event = q.pop_next()
        assert event is not None
        assert event["event_type"] == "test"
        assert event["scheduled_time"] == t

    def test_pop_empty(self):
        db = FakeFirestoreClient()
        q = EventQueue(db=db)
        assert q.pop_next() is None

    def test_chronological_order(self):
        db = FakeFirestoreClient()
        q = EventQueue(db=db)
        base = datetime(2026, 1, 1)
        times = [base + timedelta(hours=h) for h in [5, 1, 3]]
        for i, t in enumerate(times):
            q.enqueue(f"evt_{i}", t, {})

        popped_times = []
        while (evt := q.pop_next()) is not None:
            popped_times.append(evt["scheduled_time"])

        assert popped_times == sorted(popped_times)


# ---------------------------------------------------------------------------
# Driver integration test
# ---------------------------------------------------------------------------

class TestDriver:
    def test_events_processed_in_chronological_order(self):
        """Enqueue 5 events in scrambled order; verify they process chronologically
        and the SimClock reflects each event's timestamp."""
        db = FakeFirestoreClient()
        queue = EventQueue(db=db)
        clock = SimClock()

        base = datetime(2026, 1, 1)
        offsets_hours = [10, 2, 7, 1, 5]  # deliberately scrambled
        expected_order = sorted(offsets_hours)

        for i, h in enumerate(offsets_hours):
            queue.enqueue(
                event_type=f"retry_{i}",
                scheduled_time=base + timedelta(hours=h),
                payload={"attempt": i},
            )

        processed = run(clock=clock, queue=queue)

        assert len(processed) == 5

        processed_hours = [
            (evt["scheduled_time"] - base).total_seconds() / 3600
            for evt in processed
        ]
        assert processed_hours == [float(h) for h in expected_order]

        assert clock.now() == base + timedelta(hours=max(offsets_hours))
