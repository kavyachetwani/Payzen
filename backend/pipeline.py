"""Tiered approval pipeline for the AI Revenue Recovery dashboard.

Three tiers:
- Tier 1: Fully automated (retries, card updates, mandate resequences, constraints)
- Tier 2: Merchant policy applied once (SMS/call preferences, call min amount)
- Tier 3: Business decisions requiring merchant judgment (mandate_revoked offers,
  write-offs, policy exceptions)

Only Tier 3 items appear in the decisions queue.
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from simclock.sim_clock import SimClock
from simclock.test_simclock import FakeFirestoreClient
from simclock.event_queue import EventQueue

from action.graph import build_graph
from action.nodes import reset_globals
from action.compliance import get_dnd_set, reset_dnd
from action.retry_processor import (
    process_retry_event, simulate_retry_outcome, reset_success_rates,
)
from audit.logger import AuditLogger

from decision.bandit import ContextualBandit
from decision.costs import ACTION_COSTS
from decision.constraints import ConstraintTracker
from decision.stopping import UPI_ATTEMPT_MIN_HOURS
from decision.policy import max_attempts, is_retryable as check_retryable

from backend.merchant_config import MerchantConfig

DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"
BANDIT_CONFIG = Path(__file__).parent.parent / "decision" / "bandit_config.json"
RETRY_DATA = Path(__file__).parent.parent / "data" / "retry_outcomes.json"

TIER_3_CAUSES = {"mandate_revoked"}

TIER_3_RECOMMENDATIONS = {
    "mandate_revoked": {
        "type": "recovery_conversation",
        "summary": "Customer cancelled their mandate. Recommend a recovery conversation to understand the reason and offer re-enrollment or a plan adjustment.",
        "options": ["approve_conversation", "offer_downgrade", "mark_churned"],
    },
}


def _init_bandit():
    config = json.loads(BANDIT_CONFIG.read_text())
    bandit = ContextualBandit(
        epsilon=config["epsilon"],
        learning_rate=config["learning_rate"],
        seed=config["seed"],
    )
    train_data = json.loads(RETRY_DATA.read_text())
    for _ in range(config.get("n_epochs", 1)):
        shuffled = list(train_data)
        np.random.RandomState(config["seed"]).shuffle(shuffled)
        bandit.train_on_dataset(shuffled)
    return bandit


def _outcome_label(final_state: dict, is_gate_blocked: bool = False) -> str:
    if is_gate_blocked:
        return "gate_blocked"
    audit = final_state.get("audit_entry", {})
    node = audit.get("action_node", "")
    if node == "card_update_link":
        return "card_update_sent"
    if node == "mandate_resequence":
        return "mandate_resequenced"
    if node == "escalation":
        return "escalated"
    return node or "unknown"


class PipelineServer:
    """Server-side pipeline state that persists across API calls."""

    def __init__(self):
        self.records = []
        self.record_map = {}
        self.logger = None
        self.bandit = None
        self.constraint_tracker = None
        self.rng = None
        self.clock = None
        self.event_queue = None
        self.history = {}
        self.diagnosis_cache = {}
        self.pending_actions = {}
        self.business_decisions = {}
        self.payment_status = {}
        self.activity_feed = []
        self.batch_run = False
        self.merchant_config = MerchantConfig()

    def reset(self):
        self.records = json.loads(DATA_PATH.read_text())
        self.record_map = {r["payment_id"]: r for r in self.records}

        reset_globals()
        reset_dnd()
        reset_success_rates()

        self.logger = AuditLogger()
        self.bandit = _init_bandit()
        self.constraint_tracker = ConstraintTracker()
        self.rng = np.random.RandomState(42)
        self.clock = SimClock(anchor=datetime(2026, 1, 1))
        db = FakeFirestoreClient()
        self.event_queue = EventQueue(db=db)
        self.history = {}
        self.diagnosis_cache = {}
        self.pending_actions = {}
        self.business_decisions = {}
        self.payment_status = {}
        self.activity_feed = []
        self.batch_run = False

    def run_batch(self) -> dict:
        """Process all payments with tiered approval.

        Tier 1/2 actions execute immediately. Only Tier 3 (mandate_revoked
        business decisions) are queued for merchant review.
        """
        self.reset()
        self.batch_run = True

        app = build_graph()
        dnd_set = get_dnd_set()
        config = self.merchant_config

        counts = {
            "total": len(self.records),
            "auto_executed": 0,
            "business_decisions": 0,
            "gate_blocked": 0,
            "non_retryable": 0,
        }

        for r in self.records:
            initial_state = {
                "payment_id": r["payment_id"],
                "customer_id": r["customer_id"],
                "payment_method": r["payment_method"],
                "amount": r["amount"],
                "payment_record": r,
            }

            final_state = app.invoke(initial_state)

            decision = final_state.get("decision", {})
            gate = final_state.get("gate_result", {})
            diag = final_state.get("diagnosis", {})
            audit = final_state.get("audit_entry", {})
            outcome = final_state.get("action_outcome", {})

            self.diagnosis_cache[r["payment_id"]] = diag
            cause = diag.get("cause", "unknown")

            if not gate.get("approved", True):
                counts["gate_blocked"] += 1
                self._log_gate_blocked(r, final_state, diag, gate, outcome)
                self.payment_status[r["payment_id"]] = {
                    "status": "gate_blocked",
                    "cause": cause,
                    "final_outcome": "gate_blocked",
                    "amount_recovered": 0.0,
                    "action_cost": 0.0,
                    "tier": 1,
                }
                self._add_activity(r, "gate_blocked", "gate_blocked", False, 0, 0,
                                   gate.get("reason", "compliance violation"))
                continue

            is_retryable = decision.get("is_retryable", False)

            if not is_retryable:
                # Tier 3 check: mandate_revoked → business decision
                if cause in TIER_3_CAUSES:
                    counts["business_decisions"] += 1
                    self._create_business_decision(r, diag, final_state)
                    continue

                counts["non_retryable"] += 1
                self._log_non_retryable(r, final_state, diag, gate, audit, outcome)
                outcome_label = _outcome_label(final_state)
                self.payment_status[r["payment_id"]] = {
                    "status": "resolved",
                    "cause": cause,
                    "final_outcome": outcome_label,
                    "amount_recovered": audit.get("amount_recovered", 0.0),
                    "action_cost": audit.get("action_cost", 0.0),
                    "tier": 1,
                }
                self._add_activity(r, audit.get("action_node", "unknown"), outcome_label,
                                   audit.get("success", False),
                                   audit.get("amount_recovered", 0.0),
                                   audit.get("action_cost", 0.0))
                continue

            # Retryable: Tier 1/2 — auto-execute with merchant policy
            counts["auto_executed"] += 1
            action = decision.get("action_type", "auto_retry")

            # Apply merchant policy (Tier 2)
            action, policy_reason = config.apply_policy(action, r["amount"])

            # DND check
            if r["customer_id"] in dnd_set and action in ("sms_then_retry", "call_then_retry"):
                action = "auto_retry"

            self._schedule_retry(r, diag, action, gate, dnd_set)

        # Phase 2: execute all auto-scheduled retry events
        self._run_retry_loop()

        self.logger.flush_to_json()

        return counts

    def _create_business_decision(self, record, diag, final_state):
        """Create a Tier 3 business decision for merchant review."""
        pid = record["payment_id"]
        cause = diag.get("cause", "unknown")
        rec = TIER_3_RECOMMENDATIONS.get(cause, {
            "type": "review",
            "summary": f"Requires merchant review: {cause}",
            "options": ["approve", "reject"],
        })

        amount = record["amount"]
        category = record.get("payment_category", "")
        suggested_downgrade = round(amount * 0.6, 0) if amount > 5000 else None

        detail = rec["summary"]
        if suggested_downgrade:
            detail = (
                f"Customer cancelled their ₹{amount:,.0f}/month {category} mandate. "
                f"Recommend offering ₹{suggested_downgrade:,.0f}/month as an alternative, "
                f"or initiating a recovery conversation to understand their reason."
            )

        self.business_decisions[pid] = {
            "payment_id": pid,
            "customer_id": record["customer_id"],
            "amount": amount,
            "payment_method": record["payment_method"],
            "payment_category": category,
            "bank_name": record["bank_name"],
            "failure_timestamp": record["failure_timestamp"],
            "cause": cause,
            "recommendation_type": rec["type"],
            "recommendation": detail,
            "options": rec["options"],
            "suggested_downgrade": suggested_downgrade,
            "status": "pending",
            "merchant_response": None,
            "created_at": datetime.now().isoformat(),
            "tier": 3,
        }

        self.payment_status[pid] = {
            "status": "decision_pending",
            "cause": cause,
            "final_outcome": None,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "tier": 3,
        }

        self._log_non_retryable_placeholder(record, diag)

    def _log_non_retryable_placeholder(self, record, diag):
        """Log initial event for Tier 3 items (no summary yet — awaiting decision)."""
        self.logger.log_event({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "event_type": "initial_processing",
            "attempt_number": 0,
            "sim_timestamp": record["failure_timestamp"],
            "action_type": "awaiting_decision",
            "bandit_recommended_action": None,
            "actual_action": "awaiting_decision",
            "downgrade_reason": None,
            "gate_mode": "tier_3",
            "gate_approved": True,
            "compliance_notes": [],
            "outcome_success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "outcome_details": "Tier 3 business decision — awaiting merchant input",
            "timing_context": None,
            "tier": 3,
        })

    def _schedule_retry(self, record, diag, action, gate, dnd_set):
        """Schedule a retryable payment's first attempt (Tier 1/2 auto-execute)."""
        cause = diag["cause"]
        payment_method = record["payment_method"]
        failure_time = datetime.fromisoformat(record["failure_timestamp"])

        self.clock.set(failure_time)

        delay_hours = 6.0
        scheduled_time = failure_time + timedelta(hours=delay_hours)

        if payment_method == "upi_autopay":
            from decision.scheduler import _enforce_upi_spacing, _clamp_upi_time
            from decision.constraints import clamp_upi_call
            min_hours = UPI_ATTEMPT_MIN_HOURS.get(1, 24)
            scheduled_time = failure_time + timedelta(hours=max(delay_hours, min_hours))
            scheduled_time = _enforce_upi_spacing(scheduled_time, failure_time, 1)
            if action == "call_then_retry":
                scheduled_time = clamp_upi_call(scheduled_time)
            else:
                scheduled_time = _clamp_upi_time(scheduled_time)
        else:
            if action == "call_then_retry":
                from decision.constraints import clamp_call_to_rbi_hours
                scheduled_time = clamp_call_to_rbi_hours(scheduled_time)

        ct_result = self.constraint_tracker.apply_constraints(
            action, record["customer_id"], scheduled_time, record["payment_id"]
        )
        action = ct_result["action"]

        self.event_queue.enqueue(
            event_type="retry_attempt",
            scheduled_time=scheduled_time,
            payload={
                "payment_id": record["payment_id"],
                "cause": cause,
                "action_type": action,
                "attempt_number": 1,
                "action_cost": ACTION_COSTS.get(action, 0.0),
                "payment_method": payment_method,
            },
        )

        compliance_notes = []
        for v in gate.get("compliance_violations", []):
            compliance_notes.append(v.get("details", ""))

        self.logger.log_event({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "event_type": "initial_processing",
            "attempt_number": 0,
            "sim_timestamp": record["failure_timestamp"],
            "action_type": "scheduled",
            "bandit_recommended_action": action,
            "actual_action": action,
            "downgrade_reason": ct_result.get("reason"),
            "gate_mode": "auto_execute",
            "gate_approved": True,
            "compliance_notes": compliance_notes,
            "outcome_success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "outcome_details": f"retry scheduled at {scheduled_time.isoformat()}",
            "timing_context": None,
            "tier": 1,
        })

        self.payment_status[record["payment_id"]] = {
            "status": "in_progress",
            "cause": diag["cause"],
            "final_outcome": None,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "tier": 1,
        }

    def _run_retry_loop(self):
        """Phase 2: process all queued retry events."""
        while True:
            event = self.event_queue.pop_next()
            if event is None:
                break

            scheduled_time = event["scheduled_time"]
            if isinstance(scheduled_time, str):
                scheduled_time = datetime.fromisoformat(scheduled_time)

            self.clock.set(scheduled_time)

            result = process_retry_event(
                event=event,
                payment_records=self.record_map,
                bandit=self.bandit,
                constraint_tracker=self.constraint_tracker,
                event_queue=self.event_queue,
                clock=self.clock,
                rng=self.rng,
                history=self.history,
            )

            payload = event["payload"]
            pid = payload["payment_id"]
            r = self.record_map[pid]
            failure_time = datetime.fromisoformat(r["failure_timestamp"])
            days_since = (scheduled_time - failure_time).total_seconds() / 86400
            payday_dist = scheduled_time.day - 1

            actual_action = result.get("actual_action", payload["action_type"])

            self.logger.log_event({
                "payment_id": pid,
                "customer_id": r["customer_id"],
                "event_type": "retry_attempt" if result["status"] != "escalated" else "escalation_after_exhaustion",
                "attempt_number": result["attempt_number"],
                "sim_timestamp": scheduled_time.isoformat(),
                "action_type": actual_action,
                "bandit_recommended_action": payload["action_type"],
                "actual_action": actual_action,
                "downgrade_reason": None if actual_action == payload["action_type"] else "constraint_downgrade",
                "gate_mode": "auto_execute",
                "gate_approved": True,
                "compliance_notes": [],
                "outcome_success": result["status"] == "recovered",
                "amount_recovered": result["amount_recovered"],
                "action_cost": result["action_cost"],
                "outcome_details": f"{result['status']} on attempt {result['attempt_number']}",
                "timing_context": {
                    "days_since_failure": round(days_since, 1),
                    "days_since_payday": payday_dist,
                    "time_of_day": scheduled_time.hour,
                },
                "tier": 1,
            })

            if result["status"] == "recovered":
                self._log_retryable_summary(r, self.history[pid], "recovered", scheduled_time)
                self.payment_status[pid] = {
                    "status": "resolved",
                    "cause": self.diagnosis_cache.get(pid, {}).get("cause", "unknown"),
                    "final_outcome": "recovered",
                    "amount_recovered": r["amount"],
                    "action_cost": sum(a.get("cost", 0) for a in self.history[pid]),
                    "tier": 1,
                }
                self._add_activity(r, actual_action, "recovered", True,
                                   r["amount"], result["action_cost"],
                                   sim_ts=scheduled_time.isoformat())
            elif result["status"] == "escalated":
                self._log_retryable_summary(r, self.history[pid], "failed_exhausted", scheduled_time)
                self.payment_status[pid] = {
                    "status": "resolved",
                    "cause": self.diagnosis_cache.get(pid, {}).get("cause", "unknown"),
                    "final_outcome": "failed_exhausted",
                    "amount_recovered": 0.0,
                    "action_cost": sum(a.get("cost", 0) for a in self.history[pid]),
                    "tier": 1,
                }
                self._add_activity(r, actual_action, "failed_exhausted", False,
                                   0, result["action_cost"],
                                   f"exhausted after {result['attempt_number']} attempts",
                                   sim_ts=scheduled_time.isoformat())
            else:
                self._add_activity(r, actual_action, "retry_scheduled", False,
                                   0, result["action_cost"],
                                   f"attempt {result['attempt_number']} failed, next scheduled",
                                   sim_ts=scheduled_time.isoformat())

    def _add_activity(self, record, action, outcome, success, amount_recovered, cost,
                      details=None, sim_ts=None):
        """Add an entry to the activity feed."""
        self.activity_feed.append({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "amount": record["amount"],
            "action": action,
            "outcome": outcome,
            "success": success,
            "amount_recovered": amount_recovered,
            "cost": cost,
            "details": details or "",
            "sim_timestamp": sim_ts or record.get("failure_timestamp", ""),
            "cause": self.diagnosis_cache.get(record["payment_id"], {}).get("cause", "unknown"),
        })

    # ── Tier 3: Business Decisions ──

    def get_decisions(self) -> list[dict]:
        """Return pending business decisions (Tier 3 only)."""
        decisions = [d for d in self.business_decisions.values() if d["status"] == "pending"]
        decisions.sort(key=lambda d: d["amount"], reverse=True)
        return decisions

    def approve_decision(self, payment_id: str, response: str = "approve_conversation") -> dict:
        """Merchant approves a Tier 3 business decision."""
        if payment_id not in self.business_decisions:
            return {"error": "not_found", "message": f"No business decision for {payment_id}"}

        bd = self.business_decisions[payment_id]
        if bd["status"] != "pending":
            return {"error": "already_resolved", "message": f"Decision already {bd['status']}"}

        bd["status"] = "approved"
        bd["merchant_response"] = response

        record = self.record_map[payment_id]
        outcome = "escalated"

        if response == "offer_downgrade" and bd.get("suggested_downgrade"):
            outcome = "downgrade_offered"
        elif response == "mark_churned":
            outcome = "merchant_rejected"

        self.logger.log_summary({
            "payment_id": payment_id,
            "customer_id": record["customer_id"],
            "amount": record["amount"],
            "payment_method": record["payment_method"],
            "payment_category": record["payment_category"],
            "bank_name": record["bank_name"],
            "failure_timestamp": record["failure_timestamp"],
            "failure_reason_code": record["failure_reason_code"],
            "diagnosed_cause": bd["cause"],
            "diagnosis_confidence": self.diagnosis_cache.get(payment_id, {}).get("confidence", 0),
            "ground_truth_cause": record.get("ground_truth_cause", "unknown"),
            "is_retryable": False,
            "total_attempts": 0,
            "final_outcome": outcome,
            "total_amount_recovered": 0.0,
            "total_action_cost": 0.0,
            "net_recovered": 0.0,
            "resolution_sim_timestamp": self.clock.now().isoformat(),
            "attempt_history": [],
            "tier": 3,
            "merchant_decision": response,
        })

        self.payment_status[payment_id] = {
            "status": "resolved",
            "cause": bd["cause"],
            "final_outcome": outcome,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "tier": 3,
        }

        self._add_activity(record, f"decision:{response}", outcome, False, 0, 0,
                           f"merchant {response.replace('_', ' ')}")

        self.logger.flush_to_json()
        return {"payment_id": payment_id, "outcome": outcome, "response": response}

    def reject_decision(self, payment_id: str) -> dict:
        """Merchant rejects a Tier 3 business decision (mark as churned)."""
        return self.approve_decision(payment_id, response="mark_churned")

    # ── Legacy approve/reject for backwards compat ──

    def approve_action(self, payment_id: str) -> dict:
        if payment_id in self.business_decisions:
            return self.approve_decision(payment_id)
        return {"error": "not_found", "message": f"No pending action for {payment_id}"}

    def reject_action(self, payment_id: str) -> dict:
        if payment_id in self.business_decisions:
            return self.reject_decision(payment_id)
        return {"error": "not_found", "message": f"No pending action for {payment_id}"}

    def get_pending(self) -> list[dict]:
        """Legacy: return Tier 3 decisions as 'pending'."""
        return self.get_decisions()

    # ── Single Payment Test ──

    def process_single(self, record: dict) -> dict:
        """Process a single test payment through the full pipeline."""
        if not self.batch_run:
            self.reset()
            self.batch_run = True

        pid = record["payment_id"]
        self.records.append(record)
        self.record_map[pid] = record

        app = build_graph()
        dnd_set = get_dnd_set()
        config = self.merchant_config

        initial_state = {
            "payment_id": pid,
            "customer_id": record["customer_id"],
            "payment_method": record["payment_method"],
            "amount": record["amount"],
            "payment_record": record,
        }

        final_state = app.invoke(initial_state)

        decision = final_state.get("decision", {})
        gate = final_state.get("gate_result", {})
        diag = final_state.get("diagnosis", {})
        audit_entry = final_state.get("audit_entry", {})
        outcome = final_state.get("action_outcome", {})

        self.diagnosis_cache[pid] = diag
        cause = diag.get("cause", "unknown")

        steps = []
        steps.append({
            "phase": "diagnosis",
            "detail": f"Diagnosed cause: {cause}",
            "confidence": diag.get("confidence", 0),
            "cause": cause,
        })

        if not gate.get("approved", True):
            self.payment_status[pid] = {
                "status": "gate_blocked",
                "cause": cause,
                "final_outcome": "gate_blocked",
                "amount_recovered": 0.0,
                "action_cost": 0.0,
                "tier": 1,
            }
            self._add_activity(record, "gate_blocked", "gate_blocked", False, 0, 0,
                               gate.get("reason", "compliance violation"))
            steps.append({"phase": "gate", "detail": f"Blocked: {gate.get('reason', 'compliance')}", "approved": False})
            return {"payment_id": pid, "cause": cause, "tier": 1, "outcome": "gate_blocked", "steps": steps}

        steps.append({"phase": "gate", "detail": "Compliance gate passed", "approved": True})

        is_retryable = decision.get("is_retryable", False)
        action_type = decision.get("action_type", "auto_retry")

        if not is_retryable:
            if cause in TIER_3_CAUSES:
                self._create_business_decision(record, diag, final_state)
                steps.append({"phase": "decision", "detail": f"Tier 3 — business decision queued", "action": "awaiting_decision", "tier": 3})
                return {"payment_id": pid, "cause": cause, "tier": 3, "outcome": "decision_pending", "steps": steps,
                        "decision": self.business_decisions.get(pid)}

            outcome_label = _outcome_label(final_state)
            self.payment_status[pid] = {
                "status": "resolved",
                "cause": cause,
                "final_outcome": outcome_label,
                "amount_recovered": audit_entry.get("amount_recovered", 0.0),
                "action_cost": audit_entry.get("action_cost", 0.0),
                "tier": 1,
            }
            self._add_activity(record, audit_entry.get("action_node", "unknown"), outcome_label,
                               audit_entry.get("success", False),
                               audit_entry.get("amount_recovered", 0.0),
                               audit_entry.get("action_cost", 0.0))
            steps.append({"phase": "action", "detail": f"Non-retryable: {outcome_label}", "action": audit_entry.get("action_node", "unknown"), "tier": 1})
            return {"payment_id": pid, "cause": cause, "tier": 1, "outcome": outcome_label, "steps": steps}

        action_type, policy_reason = config.apply_policy(action_type, record["amount"])
        if record["customer_id"] in dnd_set and action_type in ("sms_then_retry", "call_then_retry"):
            action_type = "auto_retry"

        steps.append({
            "phase": "bandit",
            "detail": f"Bandit chose: {action_type.replace('_', ' ')}",
            "action": action_type,
            "is_retryable": True,
        })

        self._schedule_retry(record, diag, action_type, gate, dnd_set)

        saved_feed_len = len(self.activity_feed)
        self._run_retry_loop()

        retry_results = self.activity_feed[saved_feed_len:]
        status = self.payment_status.get(pid, {})
        final_outcome = status.get("final_outcome", "in_progress")

        for r_act in retry_results:
            steps.append({
                "phase": "retry",
                "detail": f"{r_act['action'].replace('_', ' ')} → {r_act['outcome']}",
                "action": r_act["action"],
                "outcome": r_act["outcome"],
                "amount_recovered": r_act.get("amount_recovered", 0),
            })

        self.logger.flush_to_json()
        return {
            "payment_id": pid,
            "cause": cause,
            "tier": status.get("tier", 1),
            "outcome": final_outcome,
            "amount_recovered": status.get("amount_recovered", 0),
            "action_cost": status.get("action_cost", 0),
            "steps": steps,
        }

    # ── Activity Feed ──

    def get_activity(self, limit: int = 50) -> list[dict]:
        """Return recent activity feed entries, newest first."""
        return list(reversed(self.activity_feed[-limit:]))

    # ── Config ──

    def get_config(self) -> dict:
        return self.merchant_config.get_all()

    def update_config(self, updates: dict) -> dict:
        return self.merchant_config.update(updates)

    # ── Overview ──

    def get_overview(self) -> dict:
        """Compute live overview metrics from current state."""
        if not self.batch_run:
            return {"error": "no_batch", "message": "Run batch first"}

        events = self.logger.get_all_events()
        summaries = self.logger.get_all_summaries()

        total_at_risk = sum(r["amount"] for r in self.records)

        total_recovered = sum(s.get("total_amount_recovered", 0) for s in summaries)
        total_cost = sum(s.get("total_action_cost", 0) for s in summaries)
        net_recovered = total_recovered - total_cost

        # Action distribution
        action_counts = Counter()
        for e in events:
            at = e.get("actual_action", e.get("action_type", "unknown"))
            action_counts[at] += 1

        # Attempt distribution
        attempt_dist = Counter()
        retryable_count = 0
        for s in summaries:
            if not s.get("is_retryable"):
                continue
            retryable_count += 1
            fo = s.get("final_outcome", "")
            if fo == "recovered":
                attempt_dist[f"attempt_{s.get('total_attempts', 1)}"] += 1
            elif fo in ("failed_exhausted", "escalated"):
                attempt_dist["escalated"] += 1

        # Compliance
        gate_blocks = sum(1 for s in summaries if s.get("final_outcome") == "gate_blocked")
        dnd_blocks = gate_blocks
        pre_debit_forces = sum(
            1 for e in events
            for n in e.get("compliance_notes", [])
            if "pre-debit" in n.lower()
        )

        # Outcome distribution
        outcome_counts = Counter(s.get("final_outcome", "unknown") for s in summaries)

        # Tier 3 pending count
        decisions_pending = len([d for d in self.business_decisions.values() if d["status"] == "pending"])

        # Cause distribution from ALL 500 diagnoses
        cause_dist = Counter(
            d.get("cause", "unknown") for d in self.diagnosis_cache.values()
        )

        # Bank distribution
        bank_stats = defaultdict(lambda: {"total": 0, "causes": Counter()})
        for s in summaries:
            bank = s.get("bank_name", "Unknown")
            bank_stats[bank]["total"] += 1
            bank_stats[bank]["causes"][s.get("diagnosed_cause", "unknown")] += 1
        bank_data = [
            {"bank": bank, "count": data["total"], "causes": dict(data["causes"])}
            for bank, data in sorted(bank_stats.items(), key=lambda x: -x[1]["total"])
        ]

        # Recovery timeline
        daily_recovery = defaultdict(float)
        daily_cost = defaultdict(float)
        for e in events:
            ts = e.get("sim_timestamp", "")[:10]
            if ts:
                daily_recovery[ts] += e.get("amount_recovered", 0)
                daily_cost[ts] += e.get("action_cost", 0)
        cumulative = 0
        cumulative_cost = 0
        timeline = []
        for day in sorted(set(daily_recovery.keys()) | set(daily_cost.keys())):
            cumulative += daily_recovery[day]
            cumulative_cost += daily_cost[day]
            timeline.append({
                "date": day,
                "recovered": round(cumulative, 0),
                "net": round(cumulative - cumulative_cost, 0),
            })

        # Exceptions
        exhausted = [s for s in summaries if s.get("final_outcome") == "failed_exhausted"]
        escalated = [s for s in summaries if s.get("final_outcome") == "escalated"]
        pending_nr = [s for s in summaries if s.get("final_outcome") in ("card_update_sent", "mandate_resequenced")]
        blocked = [s for s in summaries if s.get("final_outcome") == "gate_blocked"]

        exceptions = {
            "exhausted": {"count": len(exhausted), "amount": round(sum(s["amount"] for s in exhausted), 0)},
            "escalated": {"count": len(escalated), "amount": round(sum(s["amount"] for s in escalated), 0)},
            "pending_nr": {"count": len(pending_nr), "amount": round(sum(s["amount"] for s in pending_nr), 0)},
            "gate_blocked": {"count": len(blocked), "amount": round(sum(s["amount"] for s in blocked), 0)},
        }

        # Tier 3 pending amount
        decisions_amount = sum(d["amount"] for d in self.business_decisions.values() if d["status"] == "pending")

        return {
            "total_payments": len(self.records),
            "total_at_risk": round(total_at_risk, 2),
            "total_recovered": round(total_recovered, 2),
            "total_cost": round(total_cost, 2),
            "net_recovered": round(net_recovered, 2),
            "recovery_rate": round(net_recovered / total_at_risk, 4) if total_at_risk > 0 else 0,
            "resolved_count": len(summaries),
            "decisions_pending": decisions_pending,
            "decisions_amount": round(decisions_amount, 2),
            "action_distribution": dict(action_counts),
            "attempt_distribution": dict(attempt_dist),
            "outcome_distribution": dict(outcome_counts),
            "cause_distribution": dict(cause_dist),
            "bank_data": bank_data,
            "timeline": timeline,
            "retryable_count": retryable_count,
            "exceptions": exceptions,
            "compliance": {
                "dnd_blocks": dnd_blocks,
                "gate_blocks": gate_blocks,
                "pre_debit_forces": pre_debit_forces,
            },
            "events_logged": len(events),
            "summaries_logged": len(summaries),
            "auto_executed": sum(1 for ps in self.payment_status.values() if ps.get("tier") in (1, 2)),
            "merchant_config": self.merchant_config.get_all(),
        }

    # ── Payments ──

    def get_payments(self, status_filter=None, cause_filter=None, method_filter=None) -> list[dict]:
        """Return all payments with their current status."""
        result = []
        for r in self.records:
            pid = r["payment_id"]
            ps = self.payment_status.get(pid, {})
            diag = self.diagnosis_cache.get(pid, {})

            entry = {
                "payment_id": pid,
                "customer_id": r["customer_id"],
                "amount": r["amount"],
                "payment_method": r["payment_method"],
                "payment_category": r["payment_category"],
                "bank_name": r["bank_name"],
                "failure_timestamp": r["failure_timestamp"],
                "failure_reason_code": r["failure_reason_code"],
                "diagnosed_cause": diag.get("cause", ps.get("cause", "unknown")),
                "confidence": diag.get("confidence", 0),
                "status": ps.get("status", "unprocessed"),
                "final_outcome": ps.get("final_outcome"),
                "amount_recovered": ps.get("amount_recovered", 0.0),
                "action_cost": ps.get("action_cost", 0.0),
                "net_recovered": ps.get("amount_recovered", 0.0) - ps.get("action_cost", 0.0),
                "total_attempts": len(self.history.get(pid, [])),
                "tier": ps.get("tier"),
            }

            if status_filter and entry["status"] != status_filter:
                continue
            if cause_filter and entry["diagnosed_cause"] != cause_filter:
                continue
            if method_filter and entry["payment_method"] != method_filter:
                continue

            result.append(entry)

        return result

    def get_payment_detail(self, payment_id: str) -> dict | None:
        """Return detail view for a single payment."""
        if payment_id not in self.record_map:
            return None

        r = self.record_map[payment_id]
        ps = self.payment_status.get(payment_id, {})
        diag = self.diagnosis_cache.get(payment_id, {})
        events = self.logger.get_payment_events(payment_id)
        summary = self.logger.get_payment_summary(payment_id)
        bd = self.business_decisions.get(payment_id)

        return {
            "payment": {
                "payment_id": payment_id,
                "customer_id": r["customer_id"],
                "amount": r["amount"],
                "payment_method": r["payment_method"],
                "payment_category": r["payment_category"],
                "bank_name": r["bank_name"],
                "failure_timestamp": r["failure_timestamp"],
                "failure_reason_code": r["failure_reason_code"],
                "ground_truth_cause": r["ground_truth_cause"],
            },
            "diagnosis": {
                "cause": diag.get("cause", ps.get("cause", "unknown")),
                "confidence": diag.get("confidence", 0),
            },
            "status": ps.get("status", "unprocessed"),
            "final_outcome": ps.get("final_outcome"),
            "amount_recovered": ps.get("amount_recovered", 0.0),
            "action_cost": ps.get("action_cost", 0.0),
            "net_recovered": ps.get("amount_recovered", 0.0) - ps.get("action_cost", 0.0),
            "attempt_history": self.history.get(payment_id, []),
            "events": events,
            "summary": summary,
            "business_decision": bd,
            "tier": ps.get("tier"),
        }

    # ── Logging helpers ──

    def _log_gate_blocked(self, record, final_state, diag, gate, outcome):
        self.logger.log_event({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "event_type": "initial_processing",
            "attempt_number": 1,
            "sim_timestamp": record["failure_timestamp"],
            "action_type": "gate_blocked",
            "bandit_recommended_action": gate.get("original_action"),
            "actual_action": "gate_blocked",
            "downgrade_reason": gate.get("reason"),
            "gate_mode": gate.get("mode", "reject"),
            "gate_approved": False,
            "compliance_notes": [v.get("details", "") for v in gate.get("compliance_violations", [])],
            "outcome_success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "outcome_details": outcome.get("details", "gate blocked"),
            "timing_context": None,
            "tier": 1,
        })

        self.logger.log_summary({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "amount": record["amount"],
            "payment_method": record["payment_method"],
            "payment_category": record["payment_category"],
            "bank_name": record["bank_name"],
            "failure_timestamp": record["failure_timestamp"],
            "failure_reason_code": record["failure_reason_code"],
            "diagnosed_cause": diag.get("cause", "unknown"),
            "diagnosis_confidence": diag.get("confidence", 0),
            "ground_truth_cause": record["ground_truth_cause"],
            "is_retryable": False,
            "total_attempts": 0,
            "final_outcome": "gate_blocked",
            "total_amount_recovered": 0.0,
            "total_action_cost": 0.0,
            "net_recovered": 0.0,
            "resolution_sim_timestamp": record["failure_timestamp"],
            "attempt_history": [{
                "attempt": 0,
                "action": "gate_blocked",
                "outcome": "blocked",
                "time": record["failure_timestamp"],
                "cost": 0.0,
                "details": outcome.get("details", "gate blocked"),
            }],
        })

    def _log_non_retryable(self, record, final_state, diag, gate, audit, outcome):
        action_node = audit.get("action_node", "unknown")

        self.logger.log_event({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "event_type": "initial_processing",
            "attempt_number": 1,
            "sim_timestamp": record["failure_timestamp"],
            "action_type": action_node,
            "bandit_recommended_action": None,
            "actual_action": action_node,
            "downgrade_reason": None,
            "gate_mode": gate.get("mode", "auto_approve"),
            "gate_approved": True,
            "compliance_notes": [],
            "outcome_success": audit.get("success", False),
            "amount_recovered": audit.get("amount_recovered", 0.0),
            "action_cost": audit.get("action_cost", 0.0),
            "outcome_details": outcome.get("details", ""),
            "timing_context": None,
            "tier": 1,
        })

        outcome_label = _outcome_label(final_state)
        self.logger.log_summary({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "amount": record["amount"],
            "payment_method": record["payment_method"],
            "payment_category": record["payment_category"],
            "bank_name": record["bank_name"],
            "failure_timestamp": record["failure_timestamp"],
            "failure_reason_code": record["failure_reason_code"],
            "diagnosed_cause": diag.get("cause", "unknown"),
            "diagnosis_confidence": diag.get("confidence", 0),
            "ground_truth_cause": record["ground_truth_cause"],
            "is_retryable": False,
            "total_attempts": 1,
            "final_outcome": outcome_label,
            "total_amount_recovered": audit.get("amount_recovered", 0.0),
            "total_action_cost": audit.get("action_cost", 0.0),
            "net_recovered": audit.get("amount_recovered", 0.0) - audit.get("action_cost", 0.0),
            "resolution_sim_timestamp": record["failure_timestamp"],
            "attempt_history": [{
                "attempt": 1,
                "action": action_node,
                "outcome": "success" if audit.get("success") else "completed",
                "time": record["failure_timestamp"],
                "cost": audit.get("action_cost", 0.0),
            }],
        })

    def _log_retryable_summary(self, record, attempts, final_outcome, resolution_time):
        total_recovered = sum(a.get("recovered", 0.0) for a in attempts)
        total_cost = sum(a.get("cost", 0.0) for a in attempts)
        diag = self.diagnosis_cache.get(record["payment_id"], {})

        self.logger.log_summary({
            "payment_id": record["payment_id"],
            "customer_id": record["customer_id"],
            "amount": record["amount"],
            "payment_method": record["payment_method"],
            "payment_category": record["payment_category"],
            "bank_name": record["bank_name"],
            "failure_timestamp": record["failure_timestamp"],
            "failure_reason_code": record["failure_reason_code"],
            "diagnosed_cause": diag.get("cause", attempts[0].get("cause", "unknown") if attempts else "unknown"),
            "diagnosis_confidence": diag.get("confidence", 0.0),
            "ground_truth_cause": record["ground_truth_cause"],
            "is_retryable": True,
            "total_attempts": len(attempts),
            "final_outcome": final_outcome,
            "total_amount_recovered": total_recovered,
            "total_action_cost": total_cost,
            "net_recovered": total_recovered - total_cost,
            "resolution_sim_timestamp": resolution_time.isoformat(),
            "attempt_history": attempts,
        })
