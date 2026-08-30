"""Test Suite 4: Backend API / PipelineServer tests (tiered approval)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def server(monkeypatch_module):
    from audit.logger import AuditLogger
    monkeypatch_module.setattr(AuditLogger, "flush_to_json", lambda self: (0, 0))
    from backend.pipeline import PipelineServer
    srv = PipelineServer()
    return srv


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


class TestTieredBatch:
    def test_run_batch(self, server):
        result = server.run_batch()
        assert result["auto_executed"] >= 0
        assert result["business_decisions"] >= 0
        total = result["auto_executed"] + result["business_decisions"] + \
                result["gate_blocked"] + result["non_retryable"]
        assert total == 500, f"Total {total} != 500"

    def test_business_decisions_are_mandate_revoked(self, server):
        server.run_batch()
        decisions = server.get_decisions()
        for d in decisions:
            assert d["cause"] == "mandate_revoked"
            assert d["status"] == "pending"
            assert d["tier"] == 3

    def test_no_pending_except_tier3(self, server):
        server.run_batch()
        pending = server.get_pending()
        for p in pending:
            assert p["tier"] == 3


class TestDecisionFlow:
    def test_approve_decision(self, server):
        server.run_batch()
        decisions = server.get_decisions()
        if not decisions:
            pytest.skip("No business decisions")
        pid = decisions[0]["payment_id"]
        result = server.approve_decision(pid)
        assert "outcome" in result
        assert result["response"] == "approve_conversation"

    def test_reject_decision(self, server):
        server.run_batch()
        decisions = server.get_decisions()
        if not decisions:
            pytest.skip("No business decisions")
        pid = decisions[0]["payment_id"]
        result = server.reject_decision(pid)
        assert result["outcome"] == "merchant_rejected"

    def test_approve_nonexistent_returns_error(self, server):
        server.run_batch()
        result = server.approve_action("PAY_99999")
        assert "error" in result

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
        assert count_2 == count_1, \
            f"Second batch changed summary count: {count_1} -> {count_2}"


class TestOverviewIntegrity:
    def test_overview_after_batch(self, server):
        server.run_batch()
        ov = server.get_overview()
        assert ov["total_payments"] == 500
        assert ov["total_at_risk"] > 0
        assert "net_recovered" in ov
        assert "recovery_rate" in ov
        assert "decisions_pending" in ov
        assert "decisions_amount" in ov

    def test_payments_list(self, server):
        server.run_batch()
        payments = server.get_payments()
        assert len(payments) == 500
        for p in payments:
            assert "payment_id" in p
            assert "amount" in p
            assert "status" in p


class TestActivityFeed:
    def test_activity_after_batch(self, server):
        server.run_batch()
        activity = server.get_activity(limit=10)
        assert len(activity) <= 10
        if activity:
            a = activity[0]
            assert "payment_id" in a
            assert "action" in a
            assert "outcome" in a


class TestMerchantConfig:
    def test_get_config(self, server):
        config = server.get_config()
        assert "sms_enabled" in config
        assert "calls_enabled" in config
        assert "call_min_amount" in config

    def test_update_config(self, server):
        result = server.update_config({"call_min_amount": 5000})
        assert result["call_min_amount"] == 5000
        server.update_config({"call_min_amount": 2000})
