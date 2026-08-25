"""Backtest: tuned bandit vs naive baseline on held-out retry data.

Uses simulation-based evaluation: success probabilities are learned from
training data per (cause, action, context_bucket), then applied to test
records based on each strategy's chosen action. This way the action choice
actually affects the outcome.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS, ARMS
from decision.tune_bandit import split_retry_data

DATA_PATH = Path(__file__).parent.parent / "data" / "retry_outcomes.json"
CONFIG_PATH = Path(__file__).parent / "bandit_config.json"


def _context_bucket(record: dict) -> str:
    """Bucket context features for success rate estimation."""
    payday_near = abs(record["days_since_estimated_payday"]) <= 3
    early_retry = record["days_since_failure"] <= 1
    return f"{record['original_cause']}|payday={'near' if payday_near else 'far'}|early={'yes' if early_retry else 'no'}|attempt={record['retry_attempt_number']}"


def learn_success_rates(train: list[dict]) -> dict:
    """Learn P(success | cause, action, context_bucket) from training data."""
    counts = defaultdict(lambda: {"success": 0, "total": 0})
    cause_action = defaultdict(lambda: {"success": 0, "total": 0})

    for r in train:
        key = (_context_bucket(r), r["action_type"])
        counts[key]["total"] += 1
        if r["outcome"] == "success":
            counts[key]["success"] += 1

        ca_key = (r["original_cause"], r["action_type"])
        cause_action[ca_key]["total"] += 1
        if r["outcome"] == "success":
            cause_action[ca_key]["success"] += 1

    rates = {}
    for key, v in counts.items():
        if v["total"] >= 5:
            rates[key] = v["success"] / v["total"]

    return rates, cause_action


def get_success_prob(record: dict, action: str, rates: dict,
                     cause_action: dict) -> float:
    """Get success probability for a (record, action) pair."""
    bucket = _context_bucket(record)
    key = (bucket, action)
    if key in rates:
        return rates[key]

    ca_key = (record["original_cause"], action)
    ca = cause_action.get(ca_key, {"success": 0, "total": 1})
    if ca["total"] >= 3:
        return ca["success"] / ca["total"]

    return 0.1


def simulate_strategy(records: list[dict], action_fn, rates: dict,
                      cause_action: dict, rng: np.random.RandomState) -> dict:
    """Simulate a strategy using learned success probabilities."""
    total_at_risk = 0.0
    total_recovered = 0.0
    total_cost = 0.0
    by_cause = defaultdict(lambda: {"at_risk": 0.0, "recovered": 0.0, "cost": 0.0, "count": 0})
    action_counts = defaultdict(int)

    for r in records:
        action = action_fn(r)
        cost = ACTION_COSTS[action]
        prob = get_success_prob(r, action, rates, cause_action)
        success = rng.random() < prob
        recovered = r["amount"] if success else 0.0

        total_at_risk += r["amount"]
        total_recovered += recovered
        total_cost += cost
        action_counts[action] += 1

        c = by_cause[r["original_cause"]]
        c["at_risk"] += r["amount"]
        c["recovered"] += recovered
        c["cost"] += cost
        c["count"] += 1

    net = total_recovered - total_cost
    return {
        "total_at_risk": total_at_risk,
        "total_recovered": total_recovered,
        "total_cost": total_cost,
        "net_recovered": net,
        "net_recovery_rate": net / total_at_risk if total_at_risk > 0 else 0.0,
        "by_cause": dict(by_cause),
        "action_counts": dict(action_counts),
    }


def run():
    records = json.loads(DATA_PATH.read_text())
    config = json.loads(CONFIG_PATH.read_text())
    train, test = split_retry_data(records)

    print(f"Config: {config}")
    print(f"Test set: {len(test)} records")

    rates, cause_action = learn_success_rates(train)

    print(f"\n── Learned success rates by (cause, action) ──")
    all_causes = sorted(set(r["original_cause"] for r in train))
    print(f"  {'Cause':<22s} {'auto':>8s} {'sms':>8s} {'call':>8s}")
    print(f"  {'─' * 46}")
    for cause in all_causes:
        row = f"  {cause:<22s}"
        for action in ARMS:
            ca = cause_action.get((cause, action), {"success": 0, "total": 0})
            if ca["total"] > 0:
                rate = ca["success"] / ca["total"]
                row += f" {rate:>6.1%}"
            else:
                row += f" {'—':>7s}"
        print(row)

    bandit = ContextualBandit(
        epsilon=config["epsilon"],
        learning_rate=config["learning_rate"],
        seed=config["seed"],
    )
    for _ in range(config.get("n_epochs", 1)):
        shuffled = list(train)
        np.random.RandomState(config["seed"]).shuffle(shuffled)
        bandit.train_on_dataset(shuffled)

    # Use same RNG seed for fair comparison
    N_SIMS = 20
    base_totals = defaultdict(float)
    band_totals = defaultdict(float)
    base_by_cause = defaultdict(lambda: defaultdict(float))
    band_by_cause = defaultdict(lambda: defaultdict(float))

    for sim in range(N_SIMS):
        rng_base = np.random.RandomState(sim + 100)
        rng_band = np.random.RandomState(sim + 100)

        base = simulate_strategy(test, lambda r: "auto_retry", rates, cause_action, rng_base)
        band = simulate_strategy(test, bandit.select_action, rates, cause_action, rng_band)

        for k in ["total_at_risk", "total_recovered", "total_cost", "net_recovered"]:
            base_totals[k] += base[k]
            band_totals[k] += band[k]

        for cause in base["by_cause"]:
            b = base["by_cause"][cause]
            base_by_cause[cause]["recovered"] += b["recovered"]
            base_by_cause[cause]["cost"] += b["cost"]
            base_by_cause[cause]["count"] = b["count"]
        for cause in band["by_cause"]:
            d = band["by_cause"][cause]
            band_by_cause[cause]["recovered"] += d["recovered"]
            band_by_cause[cause]["cost"] += d["cost"]
            band_by_cause[cause]["count"] = d["count"]

    for k in base_totals:
        base_totals[k] /= N_SIMS
        band_totals[k] /= N_SIMS
    for cause in base_by_cause:
        for k in ["recovered", "cost"]:
            base_by_cause[cause][k] /= N_SIMS
            band_by_cause[cause][k] /= N_SIMS

    base_totals["net_recovery_rate"] = base_totals["net_recovered"] / base_totals["total_at_risk"]
    band_totals["net_recovery_rate"] = band_totals["net_recovered"] / band_totals["total_at_risk"]

    print(f"\n{'═' * 65}")
    print(f"{'BACKTEST COMPARISON (avg over ' + str(N_SIMS) + ' simulations)':^65s}")
    print(f"{'═' * 65}")
    print(f"  {'Metric':<30s} {'Naive Baseline':>15s} {'Tuned Bandit':>15s}")
    print(f"  {'─' * 60}")
    print(f"  {'Total ₹ at risk':<30s} {base_totals['total_at_risk']:>14,.2f} {band_totals['total_at_risk']:>14,.2f}")
    print(f"  {'Total ₹ recovered (gross)':<30s} {base_totals['total_recovered']:>14,.2f} {band_totals['total_recovered']:>14,.2f}")
    print(f"  {'Total action costs':<30s} {base_totals['total_cost']:>14,.2f} {band_totals['total_cost']:>14,.2f}")
    print(f"  {'Net ₹ recovered':<30s} {base_totals['net_recovered']:>14,.2f} {band_totals['net_recovered']:>14,.2f}")
    print(f"  {'Net recovery rate':<30s} {base_totals['net_recovery_rate']:>14.1%} {band_totals['net_recovery_rate']:>14.1%}")

    if base_totals["net_recovered"] > 0:
        uplift = (band_totals["net_recovered"] - base_totals["net_recovered"]) / base_totals["net_recovered"] * 100
    else:
        uplift = float('inf') if band_totals["net_recovered"] > 0 else 0.0
    print(f"\n  Uplift: {uplift:+.1f}%")

    # Show last simulation's action distribution
    last_band = simulate_strategy(test, bandit.select_action, rates, cause_action,
                                  np.random.RandomState(999))
    print(f"\n  Bandit action distribution (sample):")
    for action in ARMS:
        count = last_band["action_counts"].get(action, 0)
        print(f"    {action}: {count} ({count/len(test):.1%})")

    print(f"\n{'═' * 65}")
    print(f"{'BREAKDOWN BY CAUSE':^65s}")
    print(f"{'═' * 65}")
    print(f"  {'Cause':<22s} {'Baseline Net':>12s} {'Bandit Net':>12s} {'Δ':>10s} {'N':>5s}")
    print(f"  {'─' * 61}")

    all_causes = sorted(set(list(base_by_cause.keys()) + list(band_by_cause.keys())))
    for cause in all_causes:
        b = base_by_cause.get(cause, {"recovered": 0, "cost": 0, "count": 0})
        d = band_by_cause.get(cause, {"recovered": 0, "cost": 0, "count": 0})
        b_net = b["recovered"] - b["cost"]
        d_net = d["recovered"] - d["cost"]
        delta = d_net - b_net
        count = int(max(b.get("count", 0), d.get("count", 0)))
        print(f"  {cause:<22s} {b_net:>11,.2f} {d_net:>11,.2f} {delta:>+9,.2f} {count:>5d}")

    return base_totals, band_totals


if __name__ == "__main__":
    run()
