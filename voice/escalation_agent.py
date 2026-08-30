"""Hinglish escalation agent using few-shot prompted sarvam-m.

This is the ONLY LLM usage in the entire system. Uses few-shot examples
from curated transcripts to generate contextual Hinglish responses for
mandate_revoked recovery conversations.

Falls back to template-based responses when the model is unavailable.
"""

import os
import json
import random
from pathlib import Path
from typing import Optional

import yaml

from voice.conversation_state import ConversationState

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

_transcript_cache: dict[str, list] = {}


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
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
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
                "model": "sarvam-m",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.7,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None


# ── Template fallback ──

TEMPLATES = {
    "greeting": {
        "too_expensive": "Namaste! {brand_name} se bol raha hoon. Aapka ₹{amount}/month ka mandate cancel hua hai. Kya main kuch help kar sakta hoon?",
        "not_using": "Hi! {brand_name} se hoon. Aapne apna plan cancel kiya hai. Kya service use nahi ho rahi thi?",
        "switched_competitor": "Hello ji! {brand_name} se call. Plan cancel hua hai. Kya koi aur service try kar rahe hain?",
        "accidental": "Namaste! {brand_name} se hoon. Aapka mandate cancel ho gaya hai. Kya aapne intentionally kiya tha?",
        "angry_frustrated": "Namaste! {brand_name} se hoon. Aapka mandate cancel hua hai. Kya main help kar sakta hoon?",
        "unknown": "Hi! {brand_name} se call hai. Aapka mandate cancel hua hai. Kya sab theek hai?",
    },
    "empathy": {
        "too_expensive": "Main samajh sakta hoon, ₹{amount} monthly kaafi amount hai. Mushkil hota hai budget manage karna.",
        "not_using": "Samajhta hoon ji, agar use nahi ho rahi toh paisa waste lagta hai. Tension mat lo.",
        "switched_competitor": "Accha ji, samajhta hoon. Feedback ke liye shukriya.",
        "accidental": "Koi baat nahi ji, hota hai! Tension mat lo, main abhi fix kar deta hoon.",
        "angry_frustrated": "Main samajh sakta hoon aap kitne frustrated hain. Sorry aapke experience ke liye. Yeh nahi hona chahiye tha.",
        "unknown": "Samajhta hoon ji, mushkil situation hai.",
    },
    "offer": {
        "too_expensive": "Humare paas ek chhota plan hai ₹{downgrade}/month mein. Kya consider karenge?",
        "not_using": "Aap subscription pause kar sakte hain — cancel nahi. Data saved rahega.",
        "switched_competitor": "Hum bhi price match karne ki koshish kar sakte hain. Interest hai?",
        "accidental": "Link bhej raha hoon — ek tap mein wapas set ho jayega. Koi extra charge nahi.",
        "angry_frustrated": "Main yeh case senior team ko bhejta hoon. Kab convenient hoga baat karna?",
        "unknown": "Kya main koi aur tarike se help kar sakta hoon?",
    },
    "close_positive": "Bahut accha! Link SMS pe aa jayega. Dhanyavaad ji!",
    "close_callback": "Bilkul ji, jab bhi convenient ho humein call kar lena. Accha din ho!",
    "close_refused": "Koi baat nahi ji, aapki marzi. Agar kabhi zaroorat ho toh yaad rakhiye. Take care!",
    "close_escalate": "Main senior team se connect karta hoon. Aapko jaldi update milega.",
}


def _template_response(state: ConversationState, brand_name: str = "YourBrand") -> str:
    scenario = state.scenario
    downgrade = round(state.amount * 0.6)

    if state.turn_count == 0:
        template = TEMPLATES["greeting"].get(scenario, TEMPLATES["greeting"]["unknown"])
        return template.format(brand_name=brand_name, amount=state.amount)

    if state.outcome == "promise_to_pay":
        return TEMPLATES["close_positive"]
    if state.outcome == "wants_callback":
        return TEMPLATES["close_callback"]
    if state.outcome == "refused":
        return TEMPLATES["close_refused"]
    if state.outcome == "needs_human_escalation":
        return TEMPLATES["close_escalate"]

    empathy = TEMPLATES["empathy"].get(scenario, TEMPLATES["empathy"]["unknown"]).format(amount=state.amount)

    if state.turn_count <= 2:
        return empathy

    offer = TEMPLATES["offer"].get(scenario, TEMPLATES["offer"]["unknown"]).format(
        downgrade=downgrade, brand_name=brand_name, amount=state.amount
    )
    return f"{empathy} {offer}"


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
