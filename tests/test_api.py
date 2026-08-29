"""Test Suite 4: Backend API / PipelineServer tests."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def server():
    from backend.pipeline import PipelineServer
    srv = PipelineServer()
    return srv


class TestApprovalFlow:
    def test_run_batch(self, server):
        result = server.run_batch()
        assert result["auto_approved"] >= 0
        assert result["pending_approval"] >= 0
        total = result["auto_approved"] + result["pending_approval"] + \
                result["gate_blocked"] + result["non_retryable"]
        assert total == 500, f"Total {total} != 500"

    def test_approve_changes_status(self, server):
        server.run_batch()
        pending = server.get_pending()
        if not pending:
            pytest.skip("No pending actions")
        pid = pending[0]["payment_id"]
        result = server.approve_action(pid)
        assert result is not None
        assert "outcome" in result

    def test_approve_nonexistent_returns_error(self, server):
        server.run_batch()
        result = server.approve_action("PAY_99999")
        assert "error" in result

    def test_reject_changes_status(self, server):
        server.run_batch()
        pending = server.get_pending()
        if not pending:
            pytest.skip("No pending actions")
        pid = pending[0]["payment_id"]
        result = server.reject_action(pid)
        assert result is not None
        detail = server.get_payment_detail(pid)
        assert detail.get("final_outcome") == "merchant_rejected"

    def test_reject_nonexistent_returns_error(self, server):
        server.run_batch()
        result = server.reject_action("PAY_99999")
        assert "error" in result


class TestDoubleProcessing:
    def test_double_batch_no_duplicates(self, server):
        server.run_batch()
        count_1 = len(server.logger.get_all_summaries())
        server.run_batch()
        count_2 = len(server.logger.get_all_summaries())
        assert count_2 == 500, f"After double batch: {count_2} summaries (expected 500)"


class TestConcurrentApprovals:
    def test_multiple_approvals(self, server):
        server.run_batch()
        pending = server.get_pending()
        if len(pending) < 5:
            pytest.skip("Not enough pending actions")
        results = []
        for p in pending[:5]:
            r = server.approve_action(p["payment_id"])
            results.append(r)
        errors = [r for r in results if "error" in r]
        assert len(errors) == 0, f"Errors: {errors}"


class TestOverviewIntegrity:
    def test_overview_after_batch(self, server):
        server.run_batch()
        ov = server.get_overview()
        assert ov["total_payments"] == 500
        assert ov["total_at_risk"] > 0
        assert "net_recovered" in ov
        assert "recovery_rate" in ov
        assert "projected_net" in ov
        assert "pending_count" in ov

    def test_payments_list(self, server):
        server.run_batch()
        payments = server.get_payments()
        assert len(payments) == 500
        for p in payments:
            assert "payment_id" in p
            assert "amount" in p
            assert "status" in p
