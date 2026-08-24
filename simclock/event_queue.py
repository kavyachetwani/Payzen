import uuid
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore


COLLECTION = "event_queue"


def _init_firestore():
    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firestore.client()


class EventQueue:
    def __init__(self, db=None):
        self._db = db or _init_firestore()

    def enqueue(self, event_type: str, scheduled_time: datetime, payload: dict) -> str:
        event_id = uuid.uuid4().hex
        self._db.collection(COLLECTION).document(event_id).set({
            "id": event_id,
            "event_type": event_type,
            "scheduled_time": scheduled_time,
            "payload": payload,
            "status": "pending",
        })
        return event_id

    def pop_next(self) -> dict | None:
        query = (
            self._db.collection(COLLECTION)
            .where("status", "==", "pending")
            .order_by("scheduled_time")
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return None
        doc = docs[0]
        event = doc.to_dict()
        doc.reference.update({"status": "processed"})
        return event
