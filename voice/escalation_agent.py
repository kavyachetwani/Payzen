"""Hinglish escalation agent using few-shot prompted sarvam-30b.

This is the ONLY LLM usage in the entire system. Uses few-shot examples
from curated transcripts to generate contextual Hinglish responses for
mandate_revoked recovery conversations.

Falls back to context-aware template responses when the model is unavailable.
"""

import os
import json
import random
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

from voice.conversation_state import ConversationState, detect_scenario_from_message

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

_transcript_cache: dict[str, list] = {}
_sarvam_connected = False


def _load_transcripts(scenario: str) -> list[dict]:
    if scenario in _transcript_cache:
        return _transcript_cache[scenario]
    path = TRANSCRIPTS_DIR / f"{scenario}.yaml"
    if not path.exists():
        path = TRANSCRIPTS_DIR / "general_patterns.yaml"
    data = yaml.safe_load(path.read_text())
    convos = data.get("conversations", [])
    _transcript_cache[scenario] = convos
    return convos


def _pick_few_shot_examples(scenario: str, n: int = 3) -> list[dict]:
    convos = _load_transcripts(scenario)
    if len(convos) <= n:
        return convos
    return random.sample(convos, n)


def _format_few_shot_prompt(
    state: ConversationState,
    brand_name: str = "YourBrand",
) -> str:
    examples = _pick_few_shot_examples(state.scenario)

    prompt_parts = [
        "You are a Hinglish-speaking customer recovery agent for a fintech company.",
        "You speak naturally in Hinglish — Hindi sentence structure with English financial terms (EMI, SIP, mandate, UPI, auto-debit).",
        "RULES:",
        "1. Never threaten or pressure. Always empathize first.",
        "2. Keep responses under 2 sentences.",
        "3. If customer refuses, accept gracefully — do not push.",
        "4. If customer is angry, de-escalate before offering solutions.",
        "5. Use ₹ symbol for amounts, not 'Rs' or 'INR'.",
        "6. Match the customer's energy — don't be overly cheerful with an angry customer.",
        "7. Financial terms stay in English: EMI, SIP, mandate, premium, auto-debit, refund.",
        "",
        f"Brand: {brand_name}",
        f"Customer's payment: ₹{state.amount:,.0f}/month {state.payment_category}",
        f"Scenario: {state.scenario}",
        "",
        "Here are example conversations for reference:",
    ]

    for i, ex in enumerate(examples, 1):
        prompt_parts.append(f"\n--- Example {i} (outcome: {ex.get('outcome', 'unknown')}) ---")
        for turn in ex.get("turns", []):
            role_label = "Agent" if turn["role"] == "agent" else "Customer"
            text = turn["text"].replace("{brand_name}", brand_name).replace("{amount}", str(state.amount))
            prompt_parts.append(f"{role_label}: {text}")

    prompt_parts.append("\n--- Current conversation ---")
    for turn in state.turns:
        role_label = "Agent" if turn["role"] == "agent" else "Customer"
        prompt_parts.append(f"{role_label}: {turn['text']}")

    prompt_parts.append("\nAgent:")

    return "\n".join(prompt_parts)


def _call_sarvam(prompt: str) -> Optional[str]:
    global _sarvam_connected
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        print("Sarvam API failed: no SARVAM_API_KEY in environment, using template fallback")
        return None
    try:
        import requests
        resp = requests.post(
            "https://api.sarvam.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sarvam-105b-conversations",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.7,
                "reasoning_effort": None,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            if not _sarvam_connected:
                print("Sarvam API connected")
                _sarvam_connected = True
            return text
        else:
            print(f"Sarvam API failed: HTTP {resp.status_code} {resp.text[:200]}, using template fallback")
    except Exception as e:
        print(f"Sarvam API failed: {e}, using template fallback")
    return None


# ── Context-aware template fallback ──

def _classify_customer_intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["nahi chahiye", "cancel", "band karo", "bye", "dnd", "final", "nahi nahi"]):
        return "refusing"
    if any(w in t for w in ["consumer forum", "complaint", "senior", "manager", "irda", "rbi"]):
        return "escalating"
    if any(w in t for w in ["baad mein", "kal", "busy", "meeting", "later", "sochna", "dekhunga", "bataunga"]):
        return "deferring"
    if any(w in t for w in ["haan kar do", "bhej do", "set kar do", "wapas kar do", "kar leta",
                             "ready", "agree", "haan chalega", "abhi kar", "ok theek", "theek hai kar",
                             "ok done", "try karta"]):
        return "agreeing"
    if any(w in t for w in ["chalega", "match karo", "reduce", "sasta", "kam rate", "chhota plan"]):
        return "negotiating"
    if any(w in t for w in ["gussa", "angry", "bakwas", "scam", "harassment", "worst", "kharab"]):
        return "angry"
    if any(w in t for w in ["kyun", "kaise", "kab", "kitna", "kya hoga", "?"]):
        return "asking_question"
    if any(w in t for w in ["mehenga", "mehnga", "expensive", "afford", "zyada", "paisa", "budget"]):
        return "price_concern"
    if any(w in t for w in ["use nahi", "zaroorat nahi", "kaam nahi", "open nahi"]):
        return "not_using"
    if any(w in t for w in ["galti", "mistake", "accidental", "nahi kiya"]):
        return "accidental"
    if any(w in t for w in ["doosra", "switch", "competitor", "shift", "migrate"]):
        return "switched"
    return "neutral"


def _template_response(state: ConversationState, brand_name: str = "YourBrand") -> str:
    scenario = state.scenario
    amount = state.amount
    downgrade = round(amount * 0.6)
    category = state.payment_category or "subscription"

    # Greeting (first turn, no customer message yet)
    if state.turn_count == 0:
        greetings = {
            "too_expensive": f"Namaste! {brand_name} se bol raha hoon. Aapka ₹{amount:,.0f}/month ka {category} mandate cancel hua hai. Kya main kuch help kar sakta hoon?",
            "not_using": f"Hi! {brand_name} se hoon. Aapne apna {category} plan cancel kiya hai. Kya service use nahi ho rahi thi?",
            "switched_competitor": f"Hello ji! {brand_name} se call. {category} plan cancel hua hai. Kya koi aur service try kar rahe hain?",
            "accidental": f"Namaste! {brand_name} se hoon. Aapka {category} mandate cancel ho gaya hai. Kya aapne intentionally kiya tha?",
            "angry_frustrated": f"Namaste! {brand_name} se hoon. Aapka {category} mandate cancel hua hai. Kya main help kar sakta hoon?",
            "unknown": f"Hi! {brand_name} se call hai. Aapka ₹{amount:,.0f}/month ka {category} mandate cancel hua hai. Kya sab theek hai?",
        }
        return greetings.get(scenario, greetings["unknown"])

    # If outcome is terminal, give appropriate closing
    if state.outcome == "promise_to_pay":
        return f"Bahut accha! ₹{amount:,.0f}/month {category} ka mandate link SMS pe aa jayega. Dhanyavaad ji!"
    if state.outcome == "wants_callback":
        return "Bilkul ji, jab bhi convenient ho humein call kar lena. Accha din ho!"
    if state.outcome == "refused":
        return f"Koi baat nahi ji, aapki marzi. Agar kabhi {category} zaroorat ho toh yaad rakhiye. Take care!"
    if state.outcome == "needs_human_escalation":
        return "Main senior team se connect karta hoon. Aapko jaldi update milega."
    if state.outcome == "interested_in_downgrade":
        return f"Bahut accha! ₹{downgrade:,.0f}/month ka plan set kar deta hoon. Link SMS pe aayega. Dhanyavaad!"

    # Context-aware response based on what the customer actually said
    last_msg = state.get_last_customer_message() or ""
    intent = _classify_customer_intent(last_msg)

    if intent == "angry":
        return f"Main samajh sakta hoon aap kitne frustrated hain. Sorry aapke experience ke liye. Batayiye kya issue hua — main personally dekhta hoon."

    if intent == "price_concern":
        return f"Main samajh sakta hoon, ₹{amount:,.0f} monthly kaafi amount hai. Humare paas ₹{downgrade:,.0f}/month ka {category} plan hai — same core features. Kya consider karenge?"

    if intent == "not_using":
        return f"Samajhta hoon ji. Ek option hai — {category} ko 3 months ke liye pause kar sakte ho, cancel nahi. Data saved rahega. Kya pause karna chahenge?"

    if intent == "accidental":
        return f"Koi baat nahi ji, hota hai! Main abhi ek naya mandate link bhej deta hoon — ek tap mein ₹{amount:,.0f}/month {category} wapas set ho jayega."

    if intent == "switched":
        return f"Accha ji, feedback ke liye shukriya. Hum bhi ₹{downgrade:,.0f}/month pe price match karne ki koshish kar sakte hain. Interest hai?"

    if intent == "asking_question":
        if "kitna" in last_msg.lower() or "amount" in last_msg.lower():
            return f"Aapka current {category} ₹{amount:,.0f}/month hai. Reduced plan ₹{downgrade:,.0f}/month mein available hai — same core features ke saath."
        if "kab" in last_msg.lower():
            return "24 hours mein sab set ho jayega. Main personally follow up karunga."
        return f"Zaroor batata hoon. Aapka {category} ₹{amount:,.0f}/month ka hai. Kya koi specific cheez jaanni hai?"

    if intent == "negotiating":
        return f"₹{downgrade:,.0f}/month ka plan available hai. Main request daal deta hoon — confirmation 24 hours mein aayegi."

    if intent == "deferring":
        return "Bilkul ji, koi rush nahi. Kab convenient hoga call karna?"

    if intent == "refusing":
        return f"Samajh gaya ji. Agar kabhi {category} wapas chahiye toh account saved rahega. Accha din ho!"

    if intent == "agreeing":
        return f"Bahut accha! ₹{amount:,.0f}/month {category} ka mandate link bhej raha hoon SMS pe. Ek tap mein done!"

    # Default: empathy + offer based on scenario
    empathy_offer = {
        "too_expensive": f"Samajhta hoon ji. ₹{downgrade:,.0f}/month ka {category} plan bhi hai — kya details bhejoon?",
        "not_using": f"Samajhta hoon ji. {category} ko pause kar sakte hain 3 months ke liye — data safe rahega. Interest hai?",
        "switched_competitor": f"Accha ji. Hum bhi ₹{downgrade:,.0f}/month pe offer de sakte hain. Dekhna chahenge?",
        "accidental": f"Link bhej raha hoon — ek tap mein ₹{amount:,.0f}/month {category} wapas set ho jayega.",
        "angry_frustrated": "Main samajhta hoon. Batayiye kya issue tha — main personally resolve karunga.",
        "unknown": f"Main samajhta hoon ji. Kya aap batayenge kya issue hua? Main help karna chahta hoon.",
    }
    return empathy_offer.get(scenario, empathy_offer["unknown"])


class EscalationAgent:
    """Hinglish escalation agent for mandate_revoked recovery conversations."""

    def __init__(self, brand_name: str = "YourBrand", use_llm: bool = True):
        self.brand_name = brand_name
        self.use_llm = use_llm
        self.conversations: dict[str, ConversationState] = {}

    def start_conversation(
        self,
        payment_id: str,
        customer_id: str,
        amount: float,
        payment_category: str = "",
    ) -> dict:
        state = ConversationState(
            payment_id=payment_id,
            customer_id=customer_id,
            amount=amount,
            payment_category=payment_category,
        )
        self.conversations[payment_id] = state

        greeting = self._generate_response(state)
        state.add_turn("agent", greeting)

        return {
            "agent_message": greeting,
            "state": state.to_dict(),
            "conversation_ended": False,
        }

    def process_customer_message(self, payment_id: str, customer_text: str) -> dict:
        state = self.conversations.get(payment_id)
        if state is None:
            return {"error": "no_active_conversation", "payment_id": payment_id}

        state.add_turn("customer", customer_text)
        state.detect_scenario(customer_text)
        state.detect_outcome(customer_text)

        if state.should_end():
            closing = self._generate_response(state)
            state.add_turn("agent", closing)
            return {
                "agent_message": closing,
                "state": state.to_dict(),
                "conversation_ended": True,
            }

        response = self._generate_response(state)
        state.add_turn("agent", response)

        return {
            "agent_message": response,
            "state": state.to_dict(),
            "conversation_ended": state.should_end(),
        }

    def get_conversation(self, payment_id: str) -> Optional[dict]:
        state = self.conversations.get(payment_id)
        if state is None:
            return None
        return state.to_dict()

    def _generate_response(self, state: ConversationState) -> str:
        if self.use_llm:
            prompt = _format_few_shot_prompt(state, self.brand_name)
            llm_response = _call_sarvam(prompt)
            if llm_response:
                return llm_response

        return _template_response(state, self.brand_name)
