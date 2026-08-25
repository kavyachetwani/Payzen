"""Evaluate diagnosis accuracy on the held-out test split ONLY.

Prints: overall accuracy, per-cause precision/recall, confusion matrix,
confidence calibration, edge case report, and failure analysis.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

from diagnosis.db import get_connection, create_schema, load_data
from diagnosis.rules import diagnose_all

DATA_DIR = Path(__file__).parent.parent / "data"
TEST_PATH = DATA_DIR / "payments_test_stratified.json"
CONFIG_PATH = Path(__file__).parent / "best_config.json"
FULL_DATA = DATA_DIR / "failed_payments.json"

CAUSES = [
    "insufficient_funds", "bank_outage", "mandate_expired",
    "mandate_revoked", "card_expired", "afa_stuck", "ambiguous",
]


def run():
    config = json.loads(CONFIG_PATH.read_text())
    test_records = json.loads(TEST_PATH.read_text())
    test_ids = [r["payment_id"] for r in test_records]
    truth = {r["payment_id"]: r["ground_truth_cause"] for r in test_records}

    db_path = Path(__file__).parent / "eval_temp.db"
    conn = get_connection(db_path)
    create_schema(conn)
    load_data(conn, FULL_DATA)

    results = diagnose_all(conn, config, test_ids)
    pred = {r["payment_id"]: r for r in results}

    print(f"Config: {config}")
    print(f"Test set size: {len(test_ids)} records")
    print()

    # 1. Overall accuracy
    correct = sum(1 for pid in test_ids if pred[pid]["diagnosed_cause"] == truth[pid])
    total = len(test_ids)
    print(f"═══ 1. Overall Accuracy: {correct}/{total} = {correct/total:.1%} ═══")

    # 2. Per-cause precision and recall
    print(f"\n═══ 2. Per-Cause Precision & Recall ═══")
    print(f"  {'Cause':25s} {'Prec':>6s} {'Rec':>6s} {'F1':>6s} {'Support':>7s}")
    print("  " + "─" * 55)

    for cause in CAUSES:
        tp = sum(1 for pid in test_ids
                 if pred[pid]["diagnosed_cause"] == cause and truth[pid] == cause)
        fp = sum(1 for pid in test_ids
                 if pred[pid]["diagnosed_cause"] == cause and truth[pid] != cause)
        fn = sum(1 for pid in test_ids
                 if pred[pid]["diagnosed_cause"] != cause and truth[pid] == cause)
        support = tp + fn

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

        print(f"  {cause:25s} {prec:5.1%} {rec:5.1%} {f1:5.1%}  {support:5d}")

    # 3. Confusion matrix
    print(f"\n═══ 3. Confusion Matrix (rows=true, cols=predicted) ═══")
    matrix = defaultdict(lambda: defaultdict(int))
    for pid in test_ids:
        matrix[truth[pid]][pred[pid]["diagnosed_cause"]] += 1

    pred_causes = sorted(set(pred[pid]["diagnosed_cause"] for pid in test_ids))
    all_causes = sorted(set(CAUSES) | set(pred_causes))
    label = "True \\ Pred"
    header = f"  {label:20s}" + "".join(f"{c[:8]:>9s}" for c in all_causes)
    print(header)
    print("  " + "─" * (20 + 9 * len(all_causes)))
    for true_cause in CAUSES:
        row = f"  {true_cause:20s}"
        for pred_cause in all_causes:
            count = matrix[true_cause][pred_cause]
            cell = f"{count:>9d}" if count > 0 else f"{'·':>9s}"
            row += cell
        print(row)

    # 4. Confidence calibration
    print(f"\n═══ 4. Confidence Calibration ═══")
    buckets = defaultdict(lambda: {"correct": 0, "total": 0})
    for pid in test_ids:
        conf = pred[pid]["confidence"]
        bucket = f"{int(conf * 10) / 10:.1f}-{int(conf * 10) / 10 + 0.1:.1f}"
        buckets[bucket]["total"] += 1
        if pred[pid]["diagnosed_cause"] == truth[pid]:
            buckets[bucket]["correct"] += 1

    print(f"  {'Bucket':>12s} {'Count':>6s} {'Correct':>8s} {'Actual%':>8s}")
    print("  " + "─" * 38)
    for bucket in sorted(buckets.keys()):
        b = buckets[bucket]
        actual = b["correct"] / b["total"] if b["total"] > 0 else 0.0
        print(f"  {bucket:>12s} {b['total']:>6d} {b['correct']:>8d} {actual:>7.1%}")

    # 5. Edge case report
    print(f"\n═══ 5. Edge Case Report ═══")
    all_records = json.loads(FULL_DATA.read_text())
    record_map = {r["payment_id"]: r for r in all_records}

    edge_cases = {
        "missing_bin": [pid for pid in test_ids if record_map[pid]["bin"] == ""],
        "malformed_bin": [pid for pid in test_ids if record_map[pid]["bin"] == "41X"],
        "exact_afa_threshold": [pid for pid in test_ids if record_map[pid]["amount"] == 15000.00],
        "zero_history": [pid for pid in test_ids
                         if record_map[pid]["customer_prior_success_count"] == 0
                         and record_map[pid]["customer_prior_failure_count"] == 0],
        "false_positive_outage": [pid for pid in test_ids
                                   if record_map[pid]["failure_reason_code"] == "59"
                                   and truth[pid] == "insufficient_funds"],
        "reason_cause_mismatch": [pid for pid in test_ids
                                   if record_map[pid]["failure_reason_code"] == "timeout"
                                   and truth[pid] == "afa_stuck"],
    }

    for case_type, pids in edge_cases.items():
        if not pids:
            print(f"  {case_type}: (none in test set)")
            continue
        print(f"  {case_type}: {len(pids)} records")
        for pid in pids:
            r = record_map[pid]
            d = pred[pid]
            correct = "✓" if d["diagnosed_cause"] == truth[pid] else "✗"
            print(f"    {pid} | true={truth[pid]:20s} | pred={d['diagnosed_cause']:20s} "
                  f"| conf={d['confidence']:.2f} | {correct} "
                  f"| reason={r['failure_reason_code']} bin={r['bin']} amt={r['amount']}")

    # 6. Failure analysis
    print(f"\n═══ 6. Failure Analysis (all misclassified test records) ═══")
    misses = [(pid, pred[pid], truth[pid]) for pid in test_ids
              if pred[pid]["diagnosed_cause"] != truth[pid]]
    print(f"  {len(misses)} misclassified out of {total} ({len(misses)/total:.1%})")
    print()

    for pid, p, true_cause in sorted(misses, key=lambda x: -x[1]["confidence"]):
        r = record_map[pid]
        note = _explain_miss(r, p["diagnosed_cause"], true_cause)
        print(f"  {pid} | true={true_cause:20s} | pred={p['diagnosed_cause']:20s} "
              f"| conf={p['confidence']:.2f} | {note}")

    conn.close()
    db_path.unlink(missing_ok=True)


def _explain_miss(record, predicted, true_cause):
    reason = record["failure_reason_code"]
    bin_val = record["bin"]

    if true_cause == "bank_outage" and predicted != "bank_outage":
        if len(bin_val) < 4:
            return "Bad BIN → cluster rule skipped"
        return f"BIN cluster below threshold (reason={reason})"

    if true_cause == "insufficient_funds" and predicted == "bank_outage":
        return f"False positive: SBI BIN in outage window, true cause is low balance"

    if true_cause == "ambiguous":
        return f"Ambiguous by design — any prediction is a reasonable guess (reason={reason})"

    if true_cause == "afa_stuck" and predicted != "afa_stuck":
        if reason == "timeout":
            return f"Timeout masked AFA; amount_above_afa={record['amount_above_afa_threshold']}"
        return f"AFA not detected: reason={reason}, above_threshold={record['amount_above_afa_threshold']}"

    if true_cause == "insufficient_funds" and predicted == "ambiguous":
        return f"Reason={reason}, fell through all rules to ambiguous"

    if true_cause == "mandate_expired" and predicted != "mandate_expired":
        return f"Reason code was {reason}, not '14'"

    return f"Rule mismatch: reason={reason}"


if __name__ == "__main__":
    run()
