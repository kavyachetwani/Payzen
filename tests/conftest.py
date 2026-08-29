"""Shared fixtures for backbone hardening tests.

IMPORTANT: Run `python -c "from action.run_batch_multi import run; run()"` before
running these tests. The tests read from the fallback JSON files.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_PATH = ROOT / "data" / "failed_payments.json"
EVENTS_PATH = ROOT / "audit" / "audit_events_fallback.json"
SUMMARY_PATH = ROOT / "audit" / "audit_summary_fallback.json"


@pytest.fixture(scope="session")
def records():
    return json.loads(DATA_PATH.read_text())


@pytest.fixture(scope="session")
def record_map(records):
    return {r["payment_id"]: r for r in records}


@pytest.fixture(scope="session")
def events():
    if not EVENTS_PATH.exists():
        pytest.skip("No audit events file — run batch first")
    return json.loads(EVENTS_PATH.read_text())


@pytest.fixture(scope="session")
def summaries():
    if not SUMMARY_PATH.exists():
        pytest.skip("No audit summary file — run batch first")
    return json.loads(SUMMARY_PATH.read_text())
