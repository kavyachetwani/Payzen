"""Backtest: tuned bandit vs naive baseline, with and without constraints.

Uses simulation-based evaluation: success probabilities are learned from
training data per (cause, action, context_bucket), then applied to test
records based on each strategy's chosen action.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from datetime import datetime, timedelta
from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS, ARMS
from decision.constraints import ConstraintTracker
from decision.tune_bandit import split_retry_data

DATA_PATH = Path(__file__).parent.parent / "data" / "retry_outcomes.json"
CONFIG_PATH = Path(__file__).parent / "bandit_config.json"


def _context_bucket(record: dict) -> str:
    payday_near = abs(record["days_since_estimated_payday"]) <= 3
    early_retry = record["days_since_failure"] <= 1
    return (f"{record['original_cause']}|payday={'near' if payday_near else 'far'}"
            f"|early={'yes' if early_retry else 'no'}|attempt={record['retry_attempt_number']}")


def learn_success_rates(train: list[dict]) -> tuple:
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
                      cause_action: dict, rng: np.random.RandomState,
                      use_constraints: bool = False) -> dict:
    total_at_risk = 0.0
    total_recovered = 0.0
    total_cost = 0.0
    by_cause = defaultdict(lambda: {"at_risk": 0.0, "recovered": 0.0, "cost": 0.0, "count": 0})
    action_counts = defaultdict(int)
    downgrades = []
    day_call_counts = defaultdict(int)

    tracker = ConstraintTracker() if use_constraints else None

    base_time = datetime(2026, 1, 15, 9, 0, 0)

    if use_constraints:
        pending_by_day = defaultdict(list)
        for i, r in enumerate(records):
            sim_time = base_time + timedelta(hours=i * 2)
            day_key = sim_time.strftime("%Y-%m-%d")
            action = action_fn(r)
            pending_by_day[day_key].append({
                "record": r,
                "action": action,
                "amount": r["amount"],
                "payment_id": r.get("retry_id", f"R_{i}"),
                "customer_id": r.get("customer_id", f"C_{i % 80}"),
                "scheduled_time": sim_time.isoformat(),
                "sim_time": sim_time,
                "index": i,
            })

        processed = []
        for day_key in sorted(pending_by_day.keys()):
            day_items = pending_by_day[day_key]
            day_dt = datetime.strptime(day_key, "%Y-%m-%d")

            day_items = tracker.prioritize_calls(day_items, day_dt)

            for item in day_items:
                result = tracker.apply_constraints(
                    item["action"], item["customer_id"],
                    item["sim_time"], item.get("payment_id", ""),
                )
                final_action = result["action"]
                if result["downgraded"]:
                    downgrades.append(result)

                r = item["record"]
                cost = ACTION_COSTS[final_action]
                prob = get_success_prob(r, final_action, rates, cause_action)
                success = rng.random() < prob
                recovered = r["amount"] if success else 0.0

                total_at_risk += r["amount"]
                total_recovered += recovered
                total_cost += cost
                action_counts[final_action] += 1

                if final_action == "call_then_retry":
                    day_call_counts[day_key] += 1

                c = by_cause[r["original_cause"]]
                c["at_risk"] += r["amount"]
                c["recovered"] += recovered
                c["cost"] += cost
                c["count"] += 1
    else:
        for i, r in enumerate(records):
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
    result = {
        "total_at_risk": total_at_risk,
        "total_recovered": total_recovered,
        "total_cost": total_cost,
        "net_recovered": net,
        "net_recovery_rate": net / total_at_risk if total_at_risk > 0 else 0.0,
        "by_cause": dict(by_cause),
        "action_counts": dict(action_counts),
        "downgrades": downgrades,
        "day_call_counts": dict(day_call_counts),
    }
    if tracker:
        result["audit_log"] = tracker.audit_log
    return result


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

    N_SIMS = 20
    base_totals = defaultdict(float)
    uncon_totals = defaultdict(float)
    con_totals = defaultdict(float)
    base_by_cause = defaultdict(lambda: defaultdict(float))
    uncon_by_cause = defaultdict(lambda: defaultdict(float))
    con_by_cause = defaultdict(lambda: defaultdict(float))

    last_con = None
    last_uncon = None

    for sim in range(N_SIMS):
        rng_b = np.random.RandomState(sim + 100)
        rng_u = np.random.RandomState(sim + 100)
        rng_c = np.random.RandomState(sim + 100)

        base = simulate_strategy(test, lambda r: "auto_retry", rates, cause_action, rng_b)
        uncon = simulate_strategy(test, bandit.select_action, rates, cause_action, rng_u,
                                  use_constraints=False)
        con = simulate_strategy(test, bandit.select_action, rates, cause_action, rng_c,
                                use_constraints=True)

        for k in ["total_at_risk", "total_recovered", "total_cost", "net_recovered"]:
            base_totals[k] += base[k]
            uncon_totals[k] += uncon[k]
            con_totals[k] += con[k]

        for cause in base["by_cause"]:
            for m in ["recovered", "cost"]:
                base_by_cause[cause][m] += base["by_cause"][cause][m]
            base_by_cause[cause]["count"] = base["by_cause"][cause]["count"]
        for cause in uncon["by_cause"]:
            for m in ["recovered", "cost"]:
                uncon_by_cause[cause][m] += uncon["by_cause"][cause][m]
            uncon_by_cause[cause]["count"] = uncon["by_cause"][cause]["count"]
        for cause in con["by_cause"]:
            for m in ["recovered", "cost"]:
                con_by_cause[cause][m] += con["by_cause"][cause][m]
            con_by_cause[cause]["count"] = con["by_cause"][cause]["count"]

        last_con = con
        last_uncon = uncon

    for k in list(base_totals.keys()):
        base_totals[k] /= N_SIMS
        uncon_totals[k] /= N_SIMS
        con_totals[k] /= N_SIMS
    for cause in set(list(base_by_cause.keys()) + list(uncon_by_cause.keys()) + list(con_by_cause.keys())):
        for m in ["recovered", "cost"]:
            base_by_cause[cause][m] /= N_SIMS
            uncon_by_cause[cause][m] /= N_SIMS
            con_by_cause[cause][m] /= N_SIMS

    base_totals["net_recovery_rate"] = base_totals["net_recovered"] / base_totals["total_at_risk"]
    uncon_totals["net_recovery_rate"] = uncon_totals["net_recovered"] / uncon_totals["total_at_risk"]
    con_totals["net_recovery_rate"] = con_totals["net_recovered"] / con_totals["total_at_risk"]

    print(f"\n{'═' * 80}")
    print(f"{'BACKTEST COMPARISON (avg over ' + str(N_SIMS) + ' simulations)':^80s}")
    print(f"{'═' * 80}")
    print(f"  {'Metric':<28s} {'Naive':>14s} {'Constrained':>14s} {'Unconstrained':>14s}")
    print(f"  {'─' * 70}")
    print(f"  {'Total ₹ at risk':<28s} {base_totals['total_at_risk']:>13,.0f} {con_totals['total_at_risk']:>13,.0f} {uncon_totals['total_at_risk']:>13,.0f}")
    print(f"  {'Total ₹ recovered (gross)':<28s} {base_totals['total_recovered']:>13,.0f} {con_totals['total_recovered']:>13,.0f} {uncon_totals['total_recovered']:>13,.0f}")
    print(f"  {'Total action costs':<28s} {base_totals['total_cost']:>13,.0f} {con_totals['total_cost']:>13,.0f} {uncon_totals['total_cost']:>13,.0f}")
    print(f"  {'Net ₹ recovered':<28s} {base_totals['net_recovered']:>13,.0f} {con_totals['net_recovered']:>13,.0f} {uncon_totals['net_recovered']:>13,.0f}")
    print(f"  {'Net recovery rate':<28s} {base_totals['net_recovery_rate']:>13.1%} {con_totals['net_recovery_rate']:>13.1%} {uncon_totals['net_recovery_rate']:>13.1%}")

    if base_totals["net_recovered"] > 0:
        uplift_con = (con_totals["net_recovered"] - base_totals["net_recovered"]) / base_totals["net_recovered"] * 100
        uplift_uncon = (uncon_totals["net_recovered"] - base_totals["net_recovered"]) / base_totals["net_recovered"] * 100
    else:
        uplift_con = uplift_uncon = 0.0
    print(f"\n  Uplift vs baseline:  constrained {uplift_con:+.1f}%  |  unconstrained {uplift_uncon:+.1f}%")

    print(f"\n  Action distribution (last simulation):")
    print(f"  {'':20s} {'Constrained':>14s} {'Unconstrained':>14s}")
    for action in ARMS:
        con_n = last_con["action_counts"].get(action, 0)
        uncon_n = last_uncon["action_counts"].get(action, 0)
        print(f"    {action:<18s} {con_n:>5d} ({con_n/len(test):>5.1%})  {uncon_n:>5d} ({uncon_n/len(test):>5.1%})")

    print(f"\n{'═' * 80}")
    print(f"{'BREAKDOWN BY CAUSE':^80s}")
    print(f"{'═' * 80}")
    print(f"  {'Cause':<20s} {'Baseline':>10s} {'Constrained':>12s} {'Unconstr.':>12s} {'Δ con':>9s} {'N':>4s}")
    print(f"  {'─' * 67}")

    all_causes = sorted(set(list(base_by_cause.keys()) + list(uncon_by_cause.keys()) + list(con_by_cause.keys())))
    for cause in all_causes:
        b_net = base_by_cause[cause]["recovered"] - base_by_cause[cause]["cost"]
        u_net = uncon_by_cause[cause]["recovered"] - uncon_by_cause[cause]["cost"]
        c_net = con_by_cause[cause]["recovered"] - con_by_cause[cause]["cost"]
        delta = c_net - b_net
        count = int(max(base_by_cause[cause].get("count", 0),
                        con_by_cause[cause].get("count", 0)))
        print(f"  {cause:<20s} {b_net:>9,.0f} {c_net:>11,.0f} {u_net:>11,.0f} {delta:>+8,.0f} {count:>4d}")

    if last_con and last_con.get("audit_log"):
        log = last_con["audit_log"]
        print(f"\n── Constraint audit log: {len(log)} downgrades ──")
        reasons = defaultdict(int)
        for entry in log:
            reasons[entry["reason"]] += 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {count:>4d}x  {reason}")

        print(f"\n── Sample downgrades ──")
        for entry in log[:5]:
            print(f"  {entry['payment_id']}: {entry['recommended_action']} → "
                  f"{entry['actual_action']} ({entry['reason']})")

    if last_con and last_con.get("day_call_counts"):
        dc = last_con["day_call_counts"]
        busiest = max(dc, key=dc.get) if dc else None
        if busiest:
            print(f"\n── Busiest simulated day: {busiest} with {dc[busiest]} calls ──")
            if dc[busiest] >= DAILY_CALL_BUDGET:
                print(f"  Call budget of {DAILY_CALL_BUDGET} was BINDING")
            else:
                print(f"  Call budget of {DAILY_CALL_BUDGET} was NOT binding ({DAILY_CALL_BUDGET - dc[busiest]} remaining)")

    return base_totals, con_totals, uncon_totals


DAILY_CALL_BUDGET = 30

if __name__ == "__main__":
    run()
