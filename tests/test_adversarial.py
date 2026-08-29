"""Test Suite 2: Adversarial edge cases — nasty inputs through the full pipeline."""

import json
import copy
import sys
from datetime import datetime
from pathlib import Path

import pytest
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_PATH = ROOT / "data" / "failed_payments.json"


def _base_record():
    """A minimal valid payment record."""
    return {
        "payment_id": "PAY_ADV_001",
        "customer_id": "CUST_ADV_001",
        "amount": 5000.0,
        "payment_method": "enach",
        "payment_category": "emi",
        "bank_name": "SBI",
        "failure_timestamp": "2026-01-05T14:30:00",
        "failure_reason_code": "51",
        "bin": "411111",
        "amount_above_afa_threshold": 0,
        "mandate_expiry_date": "2027-01-01",
        "pre_debit_notification_sent": True,
        "ground_truth_cause": "insufficient_funds",
        "customer_prior_success_count": 5,
        "customer_prior_failure_count": 1,
    }


def _run_single_through_graph(record):
    """Run a single record through the LangGraph pipeline and return final state."""
    from diagnosis.db import build_db
    from diagnosis.rules import diagnose
    from action.graph import build_graph
    from action.nodes import reset_globals

    reset_globals()
    conn = build_db([record])
    diag = diagnose(record["payment_id"], conn)
    conn.close()

    app = build_graph()
    initial_state = {
        "payment_id": record["payment_id"],
        "customer_id": record["customer_id"],
        "payment_method": record["payment_method"],
        "amount": record["amount"],
        "payment_record": record,
    }
    final_state = app.invoke(initial_state)
    return final_state, diag


class TestDataEdgeCases:
    def test_zero_amount(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_ZERO"
        r["amount"] = 0
        state, diag = _run_single_through_graph(r)
        assert state is not None
        audit = state.get("audit_entry", {})
        assert audit.get("amount_recovered", 0) >= 0

    def test_minimum_amount(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_MIN"
        r["amount"] = 0.01
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_very_high_amount(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_HIGH"
        r["amount"] = 1000000.0
        state, diag = _run_single_through_graph(r)
        assert state is not None
        audit = state.get("audit_entry", {})
        assert audit.get("amount_recovered", 0) <= 1000000.0

    def test_missing_customer_id(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_NOCUST"
        r["customer_id"] = ""
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_missing_bank_name(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_NOBANK"
        r["bank_name"] = ""
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_missing_bin(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_NOBIN"
        r["bin"] = ""
        state, diag = _run_single_through_graph(r)
        assert diag is not None

    def test_unknown_failure_code(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_XYZZY"
        r["failure_reason_code"] = "XYZZY"
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_null_failure_timestamp(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_NOTS"
        r["failure_timestamp"] = None
        try:
            state, diag = _run_single_through_graph(r)
        except (TypeError, ValueError, AttributeError):
            pass  # Acceptable to error on null timestamp

    def test_null_mandate_expiry_with_code_14(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_NOMANDATE"
        r["failure_reason_code"] = "14"
        r["mandate_expiry_date"] = None
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_absurd_prior_counts(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_ABSURD"
        r["customer_prior_success_count"] = 99999
        r["customer_prior_failure_count"] = 99999
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_unknown_payment_method(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_BTC"
        r["payment_method"] = "bitcoin"
        state, diag = _run_single_through_graph(r)
        assert state is not None


class TestTimingEdgeCases:
    def test_midnight_timestamp(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_MIDNIGHT"
        r["failure_timestamp"] = "2026-01-05T00:00:00"
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_day_boundary_retry(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_DAYBOUND"
        r["failure_timestamp"] = "2026-01-05T23:59:59"
        state, diag = _run_single_through_graph(r)
        assert state is not None

    def test_upi_24h_boundary(self):
        r = _base_record()
        r["payment_id"] = "PAY_ADV_UPI24"
        r["payment_method"] = "upi_autopay"
        r["failure_timestamp"] = "2026-01-05T14:00:00"
        state, diag = _run_single_through_graph(r)
        assert state is not None


class TestConstraintEdgeCases:
    def test_dnd_customer_auto_retry_succeeds(self):
        """DND blocks contact but not silent retries."""
        from action.compliance import check_dnd
        result = check_dnd("CUST_DND_TEST", "auto_retry", "insufficient_funds", True)
        assert result["passed"], "auto_retry should not be blocked by DND"

    def test_dnd_customer_sms_blocked(self):
        from action.compliance import check_dnd, _load_dnd_set
        dnd = _load_dnd_set()
        if dnd:
            cust = list(dnd)[0]
            result = check_dnd(cust, "sms_then_retry", "insufficient_funds", True)
            assert not result["passed"], "SMS to DND customer should be blocked"

    def test_exactly_30_calls_budget(self):
        from decision.constraints import ConstraintTracker
        ct = ConstraintTracker()
        dt = datetime(2026, 1, 15, 10, 0)
        for i in range(30):
            result = ct.apply_constraints("call_then_retry", f"CUST_{i:04d}", dt, f"PAY_{i:04d}")
            assert result["action"] == "call_then_retry", f"Call {i+1} should be allowed"
        result = ct.apply_constraints("call_then_retry", "CUST_9999", dt, "PAY_9999")
        assert result["action"] == "sms_then_retry", "Call 31 should be downgraded"

    def test_customer_contact_limits(self):
        from decision.constraints import ConstraintTracker
        ct = ConstraintTracker()
        dt = datetime(2026, 1, 15, 10, 0)
        result = ct.apply_constraints("call_then_retry", "CUST_LIM", dt, "PAY_L1")
        assert result["action"] == "call_then_retry"
        result = ct.apply_constraints("call_then_retry", "CUST_LIM", dt, "PAY_L2")
        assert result["action"] == "sms_then_retry", "2nd call should be downgraded to SMS"
        for i in range(3):
            ct.apply_constraints("sms_then_retry", "CUST_LIM", dt, f"PAY_S{i}")
        result = ct.apply_constraints("sms_then_retry", "CUST_LIM", dt, "PAY_S4")
        assert result["action"] == "auto_retry", "4th SMS should be downgraded to auto_retry"
