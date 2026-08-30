"""Firestore audit logger with local JSON fallback.

Two collections:
- audit_events: one document per action taken (retry attempts, one-shot actions)
- audit_summary: one document per payment (final resolved state)

Writes are buffered in memory during the batch and flushed to Firestore
in batches of 500 (Firestore's max) at the end. This avoids hitting
quota limits from 1500+ individual writes.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

FALLBACK_DIR = Path(__file__).parent
EVENTS_FALLBACK = FALLBACK_DIR / "audit_events_fallback.json"
SUMMARY_FALLBACK = FALLBACK_DIR / "audit_summary_fallback.json"

FIRESTORE_BATCH_LIMIT = 100  # small batches to stay under free-tier rate limits


class AuditLogger:
    def __init__(self):
        self._db = None
        self._using_firestore = False
        self._events = []
        self._summaries = {}
        self._firestore_flushed = False

        import os
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not creds_path:
                print(f"  ⚠ GOOGLE_APPLICATION_CREDENTIALS not set — skipping Firestore")
                raise EnvironmentError("no credentials path")

            if not os.path.exists(creds_path):
                print(f"  ⚠ Credentials file not found: {creds_path}")
                raise FileNotFoundError(creds_path)

            if not firebase_admin._apps:
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred)

            self._db = firestore.client()
            self._using_firestore = True

            project_id = firebase_admin.get_app().project_id
            print(f"  ✓ Firestore connected successfully to project: {project_id}")

        except Exception as e:
            error_type = type(e).__name__
            print(f"  ⚠ Firestore unavailable: {error_type}: {e}")
            print(f"  ⚠ Falling back to local JSON files")
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
        self._events.append(doc)
        return event_id

    def log_summary(self, payment_data: dict) -> str:
        payment_id = payment_data["payment_id"]
        doc = {
            **payment_data,
            "logged_at": datetime.now().isoformat(),
        }
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

    def _commit_batch_with_retry(self, batch, label, max_retries=5):
        """Commit a Firestore batch with exponential backoff."""
        import time
        for attempt in range(max_retries):
            try:
                batch.commit()
                return True
            except Exception as e:
                wait = min(2 ** attempt, 30)
                err_str = str(e)
                is_quota = "429" in err_str or "Quota" in err_str
                if attempt < max_retries - 1 and is_quota:
                    print(f"  ⚠ {label}: rate limited, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait)
                else:
                    print(f"  ✗ {label}: failed after {attempt+1} attempts: {e}")
                    return False
        return False

    def _flush_to_firestore(self):
        """Batch-write all buffered events and summaries to Firestore.

        Uses small batches (100 docs) with exponential backoff to stay
        under the free-tier rate limits.
        """
        if not self._using_firestore or not self._db:
            return 0, 0

        import time

        events_written = 0
        summaries_written = 0

        # Batch write events
        for chunk_start in range(0, len(self._events), FIRESTORE_BATCH_LIMIT):
            chunk = self._events[chunk_start:chunk_start + FIRESTORE_BATCH_LIMIT]
            batch = self._db.batch()
            for doc in chunk:
                ref = self._db.collection("audit_events").document(doc["event_id"])
                batch.set(ref, _serialize(doc))
            if self._commit_batch_with_retry(batch, f"events {chunk_start}–{chunk_start+len(chunk)}"):
                events_written += len(chunk)
                print(f"  ✓ Firestore: wrote {events_written}/{len(self._events)} events")
            time.sleep(1)  # pace between batches

        # Batch write summaries
        summary_list = list(self._summaries.values())
        for chunk_start in range(0, len(summary_list), FIRESTORE_BATCH_LIMIT):
            chunk = summary_list[chunk_start:chunk_start + FIRESTORE_BATCH_LIMIT]
            batch = self._db.batch()
            for doc in chunk:
                pid = doc["payment_id"]
                ref = self._db.collection("audit_summary").document(pid)
                batch.set(ref, _serialize(doc))
            if self._commit_batch_with_retry(batch, f"summaries {chunk_start}–{chunk_start+len(chunk)}"):
                summaries_written += len(chunk)
                print(f"  ✓ Firestore: wrote {summaries_written}/{len(summary_list)} summaries")
            time.sleep(1)

        self._firestore_flushed = True
        return events_written, summaries_written

    def flush_to_json(self):
        """Flush buffered data to local JSON AND Firestore (if connected)."""
        # Always write local fallback
        EVENTS_FALLBACK.write_text(json.dumps(self._events, indent=2, default=str))
        summaries_list = list(self._summaries.values())
        SUMMARY_FALLBACK.write_text(json.dumps(summaries_list, indent=2, default=str))

        # Batch-flush to Firestore
        if self._using_firestore and not self._firestore_flushed:
            ev, sm = self._flush_to_firestore()
            print(f"  ✓ Firestore flush complete: {ev} events, {sm} summaries")

        return len(self._events), len(self._summaries)

    def stats(self) -> dict:
        return {
            "events_logged": len(self._events),
            "summaries_logged": len(self._summaries),
            "backend": "Firestore" if self._using_firestore else "local JSON",
            "firestore_flushed": self._firestore_flushed,
        }


def _serialize(doc: dict) -> dict:
    """Convert any non-serializable values for Firestore."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, dict):
            out[k] = _serialize(v)
        elif isinstance(v, list):
            out[k] = [_serialize(i) if isinstance(i, dict) else i for i in v]
        elif v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def load_from_fallback() -> tuple[list[dict], list[dict]]:
    events = []
    summaries = []
    if EVENTS_FALLBACK.exists():
        events = json.loads(EVENTS_FALLBACK.read_text())
    if SUMMARY_FALLBACK.exists():
        summaries = json.loads(SUMMARY_FALLBACK.read_text())
    return events, summaries
