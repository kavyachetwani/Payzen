"""Rule-based customer simulator for testing escalation conversations.

NOT an LLM — uses keyword matching and personality-driven templates.
Generates 3-5 turn conversations with deterministic behavior based on
scenario and personality parameters.
"""

import random
from typing import Optional


PERSONALITIES = {
    "cooperative": {
        "agree_prob": 0.8,
        "anger_level": 0.1,
        "patience": 5,
    },
    "hesitant": {
        "agree_prob": 0.4,
        "anger_level": 0.2,
        "patience": 4,
    },
    "resistant": {
        "agree_prob": 0.15,
        "anger_level": 0.3,
        "patience": 3,
    },
    "angry": {
        "agree_prob": 0.1,
        "anger_level": 0.8,
        "patience": 2,
    },
}

RESPONSES = {
    "too_expensive": {
        "initial": [
            "Bahut zyada ho gaya monthly. Afford nahi ho raha.",
            "Budget tight hai, isliye cancel kiya.",
            "₹{amount} bahut hai mere liye. Kam karo toh sochta hoon.",
            "Har jagah expense cut kar raha hoon.",
        ],
        "agree_downgrade": [
            "Haan woh chalega, kar do.",
            "₹{downgrade} mein? Ok theek hai.",
            "Accha, chhota plan hai? Haan try karta hoon.",
        ],
        "hesitate": [
            "Hmm... sochna padega.",
            "Abhi decide nahi kar sakta. Baad mein batata hoon.",
            "Nahi yaar, abhi kuch bhi nahi chahiye.",
        ],
        "refuse": [
            "Nahi chahiye. Final hai.",
            "Band karo sab kuch.",
            "DND pe daal do mera number.",
        ],
    },
    "not_using": {
        "initial": [
            "Use nahi ho rahi thi, paisa waste ho raha tha.",
            "Last 3 months se open nahi kiya.",
            "Zaroorat nahi hai ab.",
        ],
        "agree_downgrade": [
            "Pause ka option hai? Haan kar do.",
            "Theek hai, ek month aur try karta hoon.",
        ],
        "hesitate": [
            "Sochta hoon. Abhi nahi.",
            "Dekhta hoon, baad mein bataunga.",
        ],
        "refuse": [
            "Nahi nahi, cancel hi karo.",
            "Nahi chahiye ab.",
        ],
    },
    "switched_competitor": {
        "initial": [
            "Doosri jagah shift ho gaya. Better service mili.",
            "Competitor pe chala gaya. Unka pricing accha hai.",
            "Haan, already migrate kar chuka hoon.",
        ],
        "agree_downgrade": [
            "Match karo toh yahi rehta hoon.",
            "Accha, woh offer accha hai. Kar do.",
        ],
        "hesitate": [
            "Already doosra le liya par next year dekhunga.",
            "Hmm dekhta hoon, abhi toh shift ho gaya.",
        ],
        "refuse": [
            "Nahi, decision final hai. Thank you.",
            "Already migrate kar chuka hoon. Hassle nahi chahiye.",
        ],
    },
    "accidental": {
        "initial": [
            "Nahi nahi! Galti se ho gaya.",
            "Cancel? Maine toh nahi kiya! Kab hua yeh?",
            "Haan woh bank app mein galti se cancel ho gaya.",
        ],
        "agree_downgrade": [
            "Haan jaldi bhej do link, wapas set karna hai!",
            "Abhi kar leta hoon. Thanks!",
            "Ok done, kar liya.",
        ],
        "hesitate": [],
        "refuse": [],
    },
    "angry_frustrated": {
        "initial": [
            "3 baar call kiya support pe, kisi ne help nahi ki!",
            "Service bakwaas hai tumhari.",
            "Phir se call? Harassment hai yeh!",
            "Bahut bura experience raha. Cancel kiya.",
        ],
        "agree_downgrade": [
            "Hmm... agar sach mein fix hua hai toh theek hai.",
            "Ek last chance de raha hoon.",
        ],
        "hesitate": [
            "Pehle refund aane do. Phir dekhunga.",
            "Consumer forum jaaunga agar fix nahi hua.",
        ],
        "refuse": [
            "Mujhe koi baat nahi karni. Cancel hai matlab cancel.",
            "DND karo. Koi call mat karo.",
            "Scam hai tum log. Refund do bas.",
        ],
    },
}


class CustomerSimulator:
    """Rule-based customer simulator for testing escalation agent."""

    def __init__(
        self,
        scenario: str,
        personality: str = "hesitant",
        amount: float = 1000,
        seed: Optional[int] = None,
    ):
        self.scenario = scenario
        self.personality = PERSONALITIES.get(personality, PERSONALITIES["hesitant"])
        self.personality_name = personality
        self.amount = amount
        self.rng = random.Random(seed)
        self.turn = 0
        self.responded_initial = False

    def respond(self, agent_message: str) -> str:
        self.turn += 1
        scenario_responses = RESPONSES.get(self.scenario, RESPONSES["not_using"])
        downgrade = round(self.amount * 0.6)

        if not self.responded_initial:
            self.responded_initial = True
            options = scenario_responses["initial"]
            text = self.rng.choice(options)
            return text.format(amount=self.amount, downgrade=downgrade)

        if self.turn >= self.personality["patience"]:
            options = scenario_responses.get("refuse", ["Nahi chahiye."])
            if not options:
                options = ["Theek hai, kar do."]
            text = self.rng.choice(options)
            return text.format(amount=self.amount, downgrade=downgrade)

        roll = self.rng.random()

        if self.scenario == "accidental":
            options = scenario_responses["agree_downgrade"]
            text = self.rng.choice(options) if options else "Haan kar do."
            return text.format(amount=self.amount, downgrade=downgrade)

        if roll < self.personality["agree_prob"]:
            options = scenario_responses.get("agree_downgrade", ["Theek hai."])
            if not options:
                options = ["Theek hai."]
            text = self.rng.choice(options)
        elif roll < self.personality["agree_prob"] + 0.3:
            options = scenario_responses.get("hesitate", ["Sochta hoon."])
            if not options:
                options = ["Sochta hoon."]
            text = self.rng.choice(options)
        else:
            options = scenario_responses.get("refuse", ["Nahi chahiye."])
            if not options:
                options = ["Nahi chahiye."]
            text = self.rng.choice(options)

        return text.format(amount=self.amount, downgrade=downgrade)


def run_simulation(
    scenario: str,
    personality: str = "hesitant",
    amount: float = 1000,
    payment_category: str = "subscription",
    brand_name: str = "YourBrand",
    seed: Optional[int] = None,
    max_turns: int = 5,
) -> dict:
    """Run a complete simulated conversation and return the result."""
    from voice.escalation_agent import EscalationAgent

    agent = EscalationAgent(brand_name=brand_name, use_llm=False)
    simulator = CustomerSimulator(scenario, personality, amount, seed)

    result = agent.start_conversation(
        payment_id=f"sim_{scenario}_{seed or 0}",
        customer_id=f"cust_sim_{seed or 0}",
        amount=amount,
        payment_category=payment_category,
    )

    turns_log = [{"role": "agent", "text": result["agent_message"]}]

    for _ in range(max_turns):
        if result.get("conversation_ended"):
            break

        customer_msg = simulator.respond(result["agent_message"])
        turns_log.append({"role": "customer", "text": customer_msg})

        result = agent.process_customer_message(
            f"sim_{scenario}_{seed or 0}", customer_msg
        )
        turns_log.append({"role": "agent", "text": result["agent_message"]})

    return {
        "scenario": scenario,
        "personality": personality,
        "amount": amount,
        "turns": turns_log,
        "outcome": result["state"]["outcome"],
        "turn_count": result["state"]["turn_count"],
    }
