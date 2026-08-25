"""Epsilon-greedy contextual bandit for retry action selection."""

import numpy as np
from decision.costs import ACTION_COSTS, ARMS

CAUSES = [
    "insufficient_funds", "bank_outage", "afa_stuck",
    "mandate_expired", "mandate_revoked", "card_expired", "ambiguous",
]


def _encode_context(record: dict) -> np.ndarray:
    cause_onehot = [1.0 if record["original_cause"] == c else 0.0 for c in CAUSES]
    features = cause_onehot + [
        record["time_of_day"] / 23.0,
        record["day_of_week"] / 6.0,
        record["days_since_failure"] / 30.0,
        (record["days_since_estimated_payday"] + 15) / 30.0,
        min(record["amount"] / 50000.0, 2.0),
        record["retry_attempt_number"] / 3.0,
        float(record["pre_debit_notification_sent"]),
    ]
    return np.array(features, dtype=np.float64)


CONTEXT_DIM = len(CAUSES) + 7
NUM_ARMS = len(ARMS)


class ContextualBandit:
    def __init__(self, epsilon: float = 0.1, learning_rate: float = 0.01,
                 seed: int = 42):
        self.epsilon = epsilon
        self.lr = learning_rate
        self.rng = np.random.RandomState(seed)
        self.weights = np.zeros((NUM_ARMS, CONTEXT_DIM))
        self.bias = np.zeros(NUM_ARMS)

    def _predict_rewards(self, ctx: np.ndarray) -> np.ndarray:
        return self.weights @ ctx + self.bias

    def select_arm(self, record: dict) -> int:
        ctx = _encode_context(record)
        if self.rng.random() < self.epsilon:
            return self.rng.randint(NUM_ARMS)
        predicted = self._predict_rewards(ctx)
        return int(np.argmax(predicted))

    def select_action(self, record: dict) -> str:
        return ARMS[self.select_arm(record)]

    def update(self, record: dict, arm: int, reward: float):
        ctx = _encode_context(record)
        predicted = self._predict_rewards(ctx)
        error = reward - predicted[arm]
        self.weights[arm] += self.lr * error * ctx
        self.bias[arm] += self.lr * error

    def train_on_dataset(self, records: list[dict]):
        for r in records:
            arm_idx = ARMS.index(r["action_type"])
            reward = r["amount_recovered"] - r["action_cost"]
            self.update(r, arm_idx, reward)

    def evaluate(self, records: list[dict]) -> dict:
        total_at_risk = 0.0
        total_recovered = 0.0
        total_cost = 0.0

        for r in records:
            action = self.select_action(r)
            cost = ACTION_COSTS[action]

            success = r["outcome"] == "success"
            recovered = r["amount"] if success else 0.0

            total_at_risk += r["amount"]
            total_recovered += recovered
            total_cost += cost

        net = total_recovered - total_cost
        return {
            "total_at_risk": total_at_risk,
            "total_recovered": total_recovered,
            "total_cost": total_cost,
            "net_recovered": net,
            "net_recovery_rate": net / total_at_risk if total_at_risk > 0 else 0.0,
        }
