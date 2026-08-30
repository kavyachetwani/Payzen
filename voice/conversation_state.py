"""Conversation state tracker for escalation conversations.

Tracks scenario detection, promises, callbacks, refusals, and turn count.
Determines when a conversation should end.
"""

from dataclasses import dataclass, field
from typing import Optional


SCENARIOS = {
    "too_expensive", "not_using", "switched_competitor",
    "accidental", "angry_frustrated", "unknown",
}

TERMINAL_STATES = {"promise_to_pay", "interested_in_downgrade", "refused", "needs_human_escalation"}

MAX_TURNS = 5


@dataclass
class ConversationState:
    payment_id: str
    customer_id: str
    amount: float
    payment_category: str = ""
    scenario: str = "unknown"
    outcome: Optional[str] = None
    turn_count: int = 0
    promised_amount: Optional[float] = None
    callback_time: Optional[str] = None
    customer_sentiment: str = "neutral"
    turns: list = field(default_factory=list)

    def add_turn(self, role: str, text: str):
        self.turns.append({"role": role, "text": text})
        self.turn_count += 1

    def detect_scenario(self, customer_text: str) -> str:
        text = customer_text.lower()
        if any(w in text for w in ["galti", "mistake", "accidental", "nahi kiya"]):
            self.scenario = "accidental"
        elif any(w in text for w in ["mehnga", "expensive", "afford", "budget", "paisa", "zyada"]):
            self.scenario = "too_expensive"
        elif any(w in text for w in ["use nahi", "zaroorat nahi", "kaam nahi"]):
            self.scenario = "not_using"
        elif any(w in text for w in ["competitor", "doosra", "switch", "shift"]):
            self.scenario = "switched_competitor"
        elif any(w in text for w in ["gussa", "angry", "frustrated", "bakwaas", "scam", "harassment"]):
            self.scenario = "angry_frustrated"
        return self.scenario

    def detect_outcome(self, customer_text: str) -> Optional[str]:
        text = customer_text.lower()
        if any(w in text for w in ["nahi chahiye", "cancel hi karo", "band karo", "bye", "dnd", "final hai", "nahi nahi"]):
            self.outcome = "refused"
        elif any(w in text for w in ["consumer forum", "complaint", "senior", "manager", "irda", "rbi"]):
            self.outcome = "needs_human_escalation"
        elif any(w in text for w in ["baad mein", "kal", "callback", "phir call", "busy", "meeting", "sochta hoon", "sochna padega", "dekhunga", "bataunga"]):
            self.outcome = "wants_callback"
        elif any(w in text for w in ["haan kar do", "bhej do", "theek hai", "ok done", "set kar do", "wapas kar do", "kar leta", "try karta", "chance"]):
            self.outcome = "promise_to_pay"
        elif any(w in text for w in ["kam rate", "chhota plan", "reduce", "sasta", "match karo", "chalega"]):
            self.outcome = "interested_in_downgrade"
        return self.outcome

    def should_end(self) -> bool:
        if self.outcome in TERMINAL_STATES:
            return True
        if self.turn_count >= MAX_TURNS:
            self.outcome = "refused"
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "customer_id": self.customer_id,
            "amount": self.amount,
            "payment_category": self.payment_category,
            "scenario": self.scenario,
            "outcome": self.outcome,
            "turn_count": self.turn_count,
            "promised_amount": self.promised_amount,
            "callback_time": self.callback_time,
            "customer_sentiment": self.customer_sentiment,
            "turns": self.turns,
        }
