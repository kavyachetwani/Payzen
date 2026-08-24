"""Split the failed payments dataset into train/test sets.

Two strategies:
1. Stratified 80/20 — every ground_truth_cause appears proportionally
2. Temporal — first 80% by failure_timestamp = train, last 20% = test
"""

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

SEED = 42
DATA_DIR = Path(__file__).parent
INPUT = DATA_DIR / "failed_payments.json"


def stratified_split(records, test_ratio=0.20):
    rng = random.Random(SEED)
    by_cause = defaultdict(list)
    for r in records:
        by_cause[r["ground_truth_cause"]].append(r)

    train, test = [], []
    for cause, recs in by_cause.items():
        rng.shuffle(recs)
        n_test = max(1, int(len(recs) * test_ratio))
        test.extend(recs[:n_test])
        train.extend(recs[n_test:])

    rng.shuffle(train)
    rng.shuffle(test)
    return train, test


def temporal_split(records, train_ratio=0.80):
    sorted_recs = sorted(records, key=lambda r: r["failure_timestamp"])
    split_idx = int(len(sorted_recs) * train_ratio)
    return sorted_recs[:split_idx], sorted_recs[split_idx:]


def print_distribution(name, records, total_original):
    causes = Counter(r["ground_truth_cause"] for r in records)
    n = len(records)
    print(f"\n  {name} ({n} records, {n/total_original*100:.0f}% of total):")
    for cause in sorted(causes, key=causes.get, reverse=True):
        pct = causes[cause] / n * 100
        print(f"    {cause:25s} {causes[cause]:4d}  ({pct:5.1f}%)")


def main():
    records = json.loads(INPUT.read_text())
    total = len(records)
    print(f"Loaded {total} records from {INPUT}")

    # Stratified split
    train_s, test_s = stratified_split(records)
    (DATA_DIR / "payments_train_stratified.json").write_text(json.dumps(train_s, indent=2))
    (DATA_DIR / "payments_test_stratified.json").write_text(json.dumps(test_s, indent=2))

    print("\n── Stratified Split ──")
    print_distribution("Train (stratified)", train_s, total)
    print_distribution("Test  (stratified)", test_s, total)

    # Temporal split
    train_t, test_t = temporal_split(records)
    (DATA_DIR / "payments_train_temporal.json").write_text(json.dumps(train_t, indent=2))
    (DATA_DIR / "payments_test_temporal.json").write_text(json.dumps(test_t, indent=2))

    print("\n── Temporal Split ──")
    print_distribution("Train (temporal)", train_t, total)
    print_distribution("Test  (temporal)", test_t, total)

    # Temporal split timestamp ranges
    ts_train = sorted(r["failure_timestamp"] for r in train_t)
    ts_test = sorted(r["failure_timestamp"] for r in test_t)
    print(f"\n  Temporal train range: {ts_train[0]} → {ts_train[-1]}")
    print(f"  Temporal test  range: {ts_test[0]} → {ts_test[-1]}")


if __name__ == "__main__":
    main()
