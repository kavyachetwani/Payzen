"""Optuna-tuned contextual bandit hyperparameter search.

Uses simulation-based evaluation: success rates are learned from training
data, then the bandit's action choices are simulated against those rates.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import optuna
from decision.bandit import ContextualBandit, ARMS
from decision.costs import ACTION_COSTS

DATA_PATH = Path(__file__).parent.parent / "data" / "retry_outcomes.json"
CONFIG_PATH = Path(__file__).parent / "bandit_config.json"

SEED = 42


def split_retry_data(records: list[dict], train_ratio: float = 0.8,
                     seed: int = SEED) -> tuple:
    rng = np.random.RandomState(seed)
    indices = rng.permutation(len(records))
    split = int(len(records) * train_ratio)
    train = [records[i] for i in indices[:split]]
    test = [records[i] for i in indices[split:]]
    return train, test


def learn_cause_action_rates(records: list[dict]) -> dict:
    """Learn P(success | cause, action) from data."""
    counts = defaultdict(lambda: {"success": 0, "total": 0})
    for r in records:
        key = (r["original_cause"], r["action_type"])
        counts[key]["total"] += 1
        if r["outcome"] == "success":
            counts[key]["success"] += 1
    return {k: v["success"] / v["total"] for k, v in counts.items() if v["total"] >= 3}


def compute_simulated_reward(bandit: ContextualBandit, records: list[dict],
                             rates: dict, rng: np.random.RandomState) -> float:
    total_net = 0.0
    for r in records:
        action = bandit.select_action(r)
        cost = ACTION_COSTS[action]
        prob = rates.get((r["original_cause"], action), 0.1)
        recovered = r["amount"] if rng.random() < prob else 0.0
        total_net += recovered - cost
    return total_net


def objective(trial: optuna.Trial, train_data: list[dict],
              rates: dict) -> float:
    epsilon = trial.suggest_float("epsilon", 0.01, 0.3, log=True)
    learning_rate = trial.suggest_float("learning_rate", 0.001, 0.1, log=True)
    n_epochs = trial.suggest_int("n_epochs", 1, 5)

    bandit = ContextualBandit(epsilon=epsilon, learning_rate=learning_rate,
                              seed=SEED)
    for _ in range(n_epochs):
        shuffled = list(train_data)
        np.random.RandomState(SEED).shuffle(shuffled)
        bandit.train_on_dataset(shuffled)

    n_sims = 5
    total = 0.0
    for i in range(n_sims):
        total += compute_simulated_reward(bandit, train_data, rates,
                                          np.random.RandomState(SEED + i))
    return total / n_sims


def run():
    records = json.loads(DATA_PATH.read_text())
    train, test = split_retry_data(records)
    print(f"Retry data: {len(records)} total, {len(train)} train, {len(test)} test")

    rates = learn_cause_action_rates(train)

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(lambda trial: objective(trial, train, rates), n_trials=50)

    best = study.best_params
    print(f"\n═══ Optuna Results ({len(study.trials)} trials) ═══")
    print(f"Best hyperparameters: {best}")
    print(f"Best train net ₹ (simulated avg): {study.best_value:,.2f}")

    config = {
        "epsilon": best["epsilon"],
        "learning_rate": best["learning_rate"],
        "n_epochs": best["n_epochs"],
        "seed": SEED,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print(f"Saved to {CONFIG_PATH}")

    print(f"\nTop 5 trials:")
    trials_sorted = sorted(study.trials, key=lambda t: t.value or 0, reverse=True)
    for i, t in enumerate(trials_sorted[:5]):
        print(f"  {i+1}. eps={t.params['epsilon']:.4f} "
              f"lr={t.params['learning_rate']:.4f} "
              f"epochs={t.params['n_epochs']} "
              f"→ ₹{t.value:,.2f}")

    return config, train, test


if __name__ == "__main__":
    run()
