"""Grid search over diagnosis config parameters using ONLY the train split.

Searches over:
- BIN prefix length: 4, 5, 6
- Cluster time window (hours): 1, 2, 3, 4
- Cluster count threshold: 3, 5, 7, 10

Prints results for every combination and saves the best config.
"""

import json
import sqlite3
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diagnosis.db import create_schema, load_data, get_connection
from diagnosis.rules import diagnose_all

DATA_DIR = Path(__file__).parent.parent / "data"
TRAIN_PATH = DATA_DIR / "payments_train_stratified.json"
BEST_CONFIG_PATH = Path(__file__).parent / "best_config.json"

GRID = {
    "bin_prefix_length": [4, 5, 6],
    "cluster_time_window_hours": [1.0, 2.0, 3.0, 4.0],
    "cluster_count_threshold": [3, 5, 7, 10],
}


def evaluate_config(config: dict, conn: sqlite3.Connection,
                    train_ids: list[str], truth: dict[str, str]) -> dict:
    results = diagnose_all(conn, config, train_ids)
    correct = sum(1 for r in results if r["diagnosed_cause"] == truth[r["payment_id"]])
    total = len(results)
    accuracy = correct / total if total > 0 else 0.0

    from collections import Counter
    predicted = Counter(r["diagnosed_cause"] for r in results)

    return {"accuracy": accuracy, "correct": correct, "total": total, "predicted": predicted}


def run():
    train_records = json.loads(TRAIN_PATH.read_text())
    train_ids = [r["payment_id"] for r in train_records]
    truth = {r["payment_id"]: r["ground_truth_cause"] for r in train_records}

    db_path = Path(__file__).parent / "tune_temp.db"
    conn = get_connection(db_path)
    create_schema(conn)
    load_data(conn, DATA_DIR / "failed_payments.json")

    keys = list(GRID.keys())
    combos = list(product(*GRID.values()))

    print(f"Grid search: {len(combos)} configurations × {len(train_ids)} train records")
    print(f"{'prefix':>6s} {'window':>6s} {'thresh':>6s} │ {'accuracy':>8s} {'correct':>7s}")
    print("─" * 45)

    best_acc = 0.0
    best_config = None
    all_results = []

    for values in combos:
        config = dict(zip(keys, values))
        result = evaluate_config(config, conn, train_ids, truth)

        print(f"  {config['bin_prefix_length']:4d}   {config['cluster_time_window_hours']:4.1f}h  "
              f"{config['cluster_count_threshold']:5d}   │ {result['accuracy']:7.1%}  "
              f"{result['correct']:4d}/{result['total']}")

        all_results.append((config, result))

        if result["accuracy"] > best_acc:
            best_acc = result["accuracy"]
            best_config = config.copy()

    print("─" * 45)
    print(f"\nBest config: {best_config}")
    print(f"Best train accuracy: {best_acc:.1%}")

    BEST_CONFIG_PATH.write_text(json.dumps(best_config, indent=2))
    print(f"Saved to {BEST_CONFIG_PATH}")

    # Show top 5
    all_results.sort(key=lambda x: -x[1]["accuracy"])
    print("\nTop 5 configurations:")
    for i, (cfg, res) in enumerate(all_results[:5]):
        print(f"  {i+1}. prefix={cfg['bin_prefix_length']} "
              f"window={cfg['cluster_time_window_hours']}h "
              f"thresh={cfg['cluster_count_threshold']} "
              f"→ {res['accuracy']:.1%}")

    conn.close()
    db_path.unlink(missing_ok=True)
    return best_config


if __name__ == "__main__":
    run()
