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


def detect_scenario_from_message(message: str) -> Optional[str]:
    text = message.lower()
    if any(w in text for w in ["galti se", "mistake", "accidental", "by mistake", "nahi kiya", "galti"]):
        return "accidental"
    if any(w in text for w in ["angry", "kharab", "worst", "bakwas", "bakwaas", "complaint", "scam", "harassment", "gussa", "frustrated"]):
        return "angry_frustrated"
    if any(w in text for w in ["mehenga", "mehnga", "expensive", "afford", "zyada", "paisa", "budget", "costly"]):
        return "too_expensive"
    if any(w in text for w in ["use nahi", "zaroorat nahi", "dont want", "band karo", "dont need", "kaam nahi", "open nahi"]):
        return "not_using"
    if any(w in text for w in ["doosra", "switch", "competitor", "better option", "shift", "migrate"]):
        return "switched_competitor"
    return None


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
        detected = detect_scenario_from_message(customer_text)
        if detected:
            self.scenario = detected
        return self.scenario

    def detect_outcome(self, customer_text: str) -> Optional[str]:
        text = customer_text.lower()

        # Refusal — clear intent to stop
        if any(w in text for w in ["nahi chahiye", "cancel hi karo", "cancel kiya", "band karo", "bye", "dnd", "final hai", "refund do"]):
            self.outcome = "refused"
            return self.outcome

        # Human escalation — regulatory/legal threats or manager requests
        if any(w in text for w in ["consumer forum", "complaint karunga", "senior", "manager", "irda", "rbi ko"]):
            self.outcome = "needs_human_escalation"
            return self.outcome

        # Callback — explicit deferral with time reference
        if any(w in text for w in ["baad mein", "kal", "callback", "phir call", "busy hoon", "meeting mein",
                                    "sochna padega", "dekhunga", "bataunga", "next week", "later"]):
            self.outcome = "wants_callback"
            return self.outcome

        # Promise to pay — explicit agreement to act NOW
        if any(w in text for w in ["haan kar do", "bhej do link", "set kar do", "wapas kar do",
                                    "ready hoon", "agree", "set up karo", "kar leta hoon",
                                    "haan chalega", "abhi kar", "ok done", "ok theek hai",
                                    "try karta", "try karti", "chance de"]):
            self.outcome = "promise_to_pay"
            return self.outcome

        # Interested in downgrade — price negotiation or acceptance of lower offer
        if any(w in text for w in ["kam rate", "chhota plan", "reduce karo", "sasta", "match karo",
                                    "woh chalega", "ok chalega"]):
            self.outcome = "interested_in_downgrade"
            return self.outcome

        # "theek hai" alone is acknowledgment, NOT a promise — don't set outcome
        # "sab theek hai" is customer saying they're fine — don't set outcome
        return self.outcome

    def should_end(self) -> bool:
        if self.outcome in TERMINAL_STATES:
            return True
        if self.turn_count >= MAX_TURNS:
            self.outcome = "refused"
            return True
        return False

    def get_last_customer_message(self) -> Optional[str]:
        for turn in reversed(self.turns):
            if turn["role"] == "customer":
                return turn["text"]
        return None

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
