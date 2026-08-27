"""Firestore audit logger with local JSON fallback.

Two collections:
- audit_events: one document per action taken (retry attempts, one-shot actions)
- audit_summary: one document per payment (final resolved state)

Falls back to local JSON files if Firestore is unavailable.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

FALLBACK_DIR = Path(__file__).parent
EVENTS_FALLBACK = FALLBACK_DIR / "audit_events_fallback.json"
SUMMARY_FALLBACK = FALLBACK_DIR / "audit_summary_fallback.json"


class AuditLogger:
    def __init__(self):
        self._db = None
        self._using_firestore = False
        self._events = []
        self._summaries = {}

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            if not firebase_admin._apps:
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(cred)
            self._db = firestore.client()
            self._using_firestore = True
        except Exception:
            print("  ⚠ Firestore unavailable — falling back to local JSON files")
            self._using_firestore = False

    @property
    def using_firestore(self) -> bool:
        return self._using_firestore

    def log_event(self, event_data: dict) -> str:
        event_id = uuid.uuid4().hex
        doc = {
            "event_id": event_id,
            **event_data,
            "logged_at": datetime.now().isoformat(),
        }

        if self._using_firestore:
            try:
                self._db.collection("audit_events").document(event_id).set(doc)
            except Exception as e:
                print(f"  ⚠ Firestore write failed: {e}")

        self._events.append(doc)
        return event_id

    def log_summary(self, payment_data: dict) -> str:
        payment_id = payment_data["payment_id"]
        doc = {
            **payment_data,
            "logged_at": datetime.now().isoformat(),
        }

        if self._using_firestore:
            try:
                self._db.collection("audit_summary").document(payment_id).set(doc)
            except Exception as e:
                print(f"  ⚠ Firestore write failed: {e}")

        self._summaries[payment_id] = doc
        return payment_id

    def get_payment_events(self, payment_id: str) -> list[dict]:
        events = [e for e in self._events if e.get("payment_id") == payment_id]
        return sorted(events, key=lambda e: e.get("attempt_number", 0))

    def get_payment_summary(self, payment_id: str) -> dict | None:
        return self._summaries.get(payment_id)

    def get_all_summaries(self) -> list[dict]:
        return list(self._summaries.values())

    def get_all_events(self) -> list[dict]:
        return list(self._events)

    def flush_to_json(self):
        EVENTS_FALLBACK.write_text(json.dumps(self._events, indent=2, default=str))
        summaries_list = list(self._summaries.values())
        SUMMARY_FALLBACK.write_text(json.dumps(summaries_list, indent=2, default=str))
        return len(self._events), len(self._summaries)

    def stats(self) -> dict:
        return {
            "events_logged": len(self._events),
            "summaries_logged": len(self._summaries),
            "backend": "Firestore" if self._using_firestore else "local JSON",
        }


def load_from_fallback() -> tuple[list[dict], list[dict]]:
    events = []
    summaries = []
    if EVENTS_FALLBACK.exists():
        events = json.loads(EVENTS_FALLBACK.read_text())
    if SUMMARY_FALLBACK.exists():
        summaries = json.loads(SUMMARY_FALLBACK.read_text())
    return events, summaries
