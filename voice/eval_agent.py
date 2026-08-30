"""Evaluation framework for the Hinglish escalation agent.

Runs 10 held-out scenarios with rubric scoring:
- Empathy shown (0-2)
- Hinglish naturalness (0-2)
- Outcome appropriate for scenario (0-2)
- Turn efficiency (0-2)
- No pressure / graceful handling (0-2)
Total: 0-10 per scenario
"""

from voice.customer_simulator import run_simulation

EVAL_SCENARIOS = [
    {"scenario": "too_expensive", "personality": "cooperative", "amount": 5000, "seed": 100},
    {"scenario": "too_expensive", "personality": "resistant", "amount": 15000, "seed": 101},
    {"scenario": "not_using", "personality": "hesitant", "amount": 999, "seed": 200},
    {"scenario": "not_using", "personality": "cooperative", "amount": 2499, "seed": 201},
    {"scenario": "switched_competitor", "personality": "resistant", "amount": 1499, "seed": 300},
    {"scenario": "accidental", "personality": "cooperative", "amount": 10000, "seed": 400},
    {"scenario": "angry_frustrated", "personality": "angry", "amount": 3000, "seed": 500},
    {"scenario": "angry_frustrated", "personality": "hesitant", "amount": 8000, "seed": 501},
    {"scenario": "too_expensive", "personality": "angry", "amount": 45000, "seed": 102},
    {"scenario": "not_using", "personality": "resistant", "amount": 699, "seed": 202},
]

EXPECTED_OUTCOMES = {
    ("too_expensive", "cooperative"): ["promise_to_pay", "interested_in_downgrade"],
    ("too_expensive", "resistant"): ["refused", "wants_callback"],
    ("too_expensive", "angry"): ["refused", "needs_human_escalation", "wants_callback"],
    ("not_using", "hesitant"): ["promise_to_pay", "interested_in_downgrade", "wants_callback"],
    ("not_using", "cooperative"): ["promise_to_pay", "interested_in_downgrade"],
    ("not_using", "resistant"): ["refused", "wants_callback"],
    ("switched_competitor", "resistant"): ["refused"],
    ("accidental", "cooperative"): ["promise_to_pay"],
    ("angry_frustrated", "angry"): ["refused", "needs_human_escalation"],
    ("angry_frustrated", "hesitant"): ["wants_callback", "needs_human_escalation", "refused"],
}

HINGLISH_MARKERS = [
    "ji", "hoon", "hai", "hain", "kya", "nahi", "aap", "aapka", "aapke",
    "kar", "karna", "bhej", "main", "mein", "toh", "bhi", "abhi",
    "dhanyavaad", "shukriya", "namaste", "accha",
]

FINANCIAL_TERMS_EN = [
    "EMI", "SIP", "mandate", "auto-debit", "premium", "subscription",
    "refund", "credit", "payment", "plan", "link", "SMS",
]

PRESSURE_PHRASES = [
    "aakhri mauka", "last chance", "abhi nahi toh", "offer khatam",
    "sirf aaj", "jaldi karo", "time nahi hai",
]


def _score_empathy(turns: list[dict]) -> int:
    agent_texts = [t["text"].lower() for t in turns if t["role"] == "agent"]
    empathy_words = ["samajh", "sorry", "mushkil", "frustrat", "tension mat", "koi baat nahi"]
    count = sum(1 for text in agent_texts for w in empathy_words if w in text)
    if count >= 2:
        return 2
    if count >= 1:
        return 1
    return 0


def _score_hinglish(turns: list[dict]) -> int:
    agent_texts = " ".join(t["text"].lower() for t in turns if t["role"] == "agent")
    hindi_count = sum(1 for m in HINGLISH_MARKERS if m in agent_texts)
    en_count = sum(1 for t in FINANCIAL_TERMS_EN if t.lower() in agent_texts)
    if hindi_count >= 3 and en_count >= 1:
        return 2
    if hindi_count >= 2:
        return 1
    return 0


def _score_outcome(scenario: str, personality: str, outcome: str) -> int:
    expected = EXPECTED_OUTCOMES.get((scenario, personality), [])
    if outcome in expected:
        return 2
    if outcome is not None:
        return 1
    return 0


def _score_efficiency(turn_count: int) -> int:
    if turn_count <= 4:
        return 2
    if turn_count <= 6:
        return 1
    return 0


def _score_no_pressure(turns: list[dict]) -> int:
    agent_texts = " ".join(t["text"].lower() for t in turns if t["role"] == "agent")
    pressure_count = sum(1 for p in PRESSURE_PHRASES if p in agent_texts)
    if pressure_count == 0:
        return 2
    if pressure_count == 1:
        return 1
    return 0


def evaluate_scenario(config: dict) -> dict:
    result = run_simulation(
        scenario=config["scenario"],
        personality=config["personality"],
        amount=config["amount"],
        seed=config["seed"],
        brand_name="TestBrand",
    )

    scores = {
        "empathy": _score_empathy(result["turns"]),
        "hinglish": _score_hinglish(result["turns"]),
        "outcome": _score_outcome(config["scenario"], config["personality"], result["outcome"]),
        "efficiency": _score_efficiency(result["turn_count"]),
        "no_pressure": _score_no_pressure(result["turns"]),
    }
    scores["total"] = sum(scores.values())

    return {
        "config": config,
        "outcome": result["outcome"],
        "turn_count": result["turn_count"],
        "scores": scores,
        "turns": result["turns"],
    }


def run_eval() -> dict:
    """Run all 10 evaluation scenarios and return aggregate results."""
    results = []
    total_score = 0
    max_score = len(EVAL_SCENARIOS) * 10

    for config in EVAL_SCENARIOS:
        result = evaluate_scenario(config)
        results.append(result)
        total_score += result["scores"]["total"]

    category_totals = {k: 0 for k in ["empathy", "hinglish", "outcome", "efficiency", "no_pressure"]}
    for r in results:
        for k, v in r["scores"].items():
            if k != "total":
                category_totals[k] += v

    return {
        "total_score": total_score,
        "max_score": max_score,
        "percentage": round(total_score / max_score * 100, 1),
        "category_scores": category_totals,
        "category_max": {k: len(EVAL_SCENARIOS) * 2 for k in category_totals},
        "scenarios": results,
    }


if __name__ == "__main__":
    import json
    results = run_eval()
    print(f"\nEscalation Agent Eval Results")
    print(f"{'='*40}")
    print(f"Total: {results['total_score']}/{results['max_score']} ({results['percentage']}%)")
    print(f"\nCategory breakdown:")
    for cat, score in results["category_scores"].items():
        max_s = results["category_max"][cat]
        print(f"  {cat:15s}: {score}/{max_s}")
    print(f"\nPer-scenario:")
    for r in results["scenarios"]:
        c = r["config"]
        outcome_str = r['outcome'] or 'none'
        print(f"  {c['scenario']:20s} ({c['personality']:12s}) → {outcome_str:25s} score={r['scores']['total']}/10")
