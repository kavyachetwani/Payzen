"""Test Suite 1C: Diagnosis accuracy and integrity."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_PATH = ROOT / "data" / "failed_payments.json"


@pytest.fixture(scope="module")
def diagnosis_results():
    records = json.loads(DATA_PATH.read_text())

    from diagnosis.db import build_db
    conn = build_db(records)

    from diagnosis.rules import diagnose
    results = []
    for r in records:
        diag = diagnose(r["payment_id"], conn)
        results.append({
            "payment_id": r["payment_id"],
            "diagnosed_cause": diag.get("diagnosed_cause", diag.get("cause")),
            "confidence": diag.get("confidence", 0),
            "ground_truth": r["ground_truth_cause"],
        })
    conn.close()
    return results


def test_no_none_diagnosis(diagnosis_results):
    for d in diagnosis_results:
        assert d["diagnosed_cause"] is not None, f"{d['payment_id']}: diagnosed_cause is None"
        assert d["diagnosed_cause"] != "", f"{d['payment_id']}: diagnosed_cause is empty"


def test_no_zero_or_negative_confidence(diagnosis_results):
    for d in diagnosis_results:
        assert d["confidence"] > 0, f"{d['payment_id']}: confidence {d['confidence']} <= 0"


def test_overall_accuracy_above_90(diagnosis_results):
    correct = sum(1 for d in diagnosis_results if d["diagnosed_cause"] == d["ground_truth"])
    accuracy = correct / len(diagnosis_results)
    assert accuracy >= 0.90, f"Accuracy {accuracy:.1%} below 90% threshold"


def test_accuracy_above_93(diagnosis_results):
    correct = sum(1 for d in diagnosis_results if d["diagnosed_cause"] == d["ground_truth"])
    accuracy = correct / len(diagnosis_results)
    assert accuracy >= 0.93, f"Accuracy {accuracy:.1%} below 93% — expected ~95%"


def test_all_diagnoses_are_known_causes(diagnosis_results):
    known = {"insufficient_funds", "bank_outage", "afa_stuck", "card_expired",
             "mandate_expired", "mandate_revoked", "ambiguous"}
    for d in diagnosis_results:
        assert d["diagnosed_cause"] in known, \
            f"{d['payment_id']}: unknown cause '{d['diagnosed_cause']}'"


def test_confidence_bounded_zero_one(diagnosis_results):
    for d in diagnosis_results:
        assert 0 < d["confidence"] <= 1.0, \
            f"{d['payment_id']}: confidence {d['confidence']} out of (0, 1] range"
