"""Pipeline logic refactored for the dashboard backend.

Two modes:
- run_batch(): Phase 1 processing — auto-approved actions execute immediately,
  require_approval actions are queued as pending
- approve_action(): Executes a pending action, potentially schedules retries
- process_pending_retries(): Processes any retry events that are due
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

DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"
BANDIT_CONFIG = Path(__file__).parent.parent / "decision" / "bandit_config.json"
RETRY_DATA = Path(__file__).parent.parent / "data" / "retry_outcomes.json"


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
        self.payment_status = {}
        self.batch_run = False

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
        self.payment_status = {}
        self.batch_run = False

    def run_batch(self) -> dict:
        """Phase 1: process all payments. Auto-approved execute; require_approval queued."""
        self.reset()
        self.batch_run = True

        app = build_graph()
        dnd_set = get_dnd_set()

        counts = {
            "total": len(self.records),
            "auto_approved": 0,
            "pending_approval": 0,
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

            if not gate.get("approved", True):
                counts["gate_blocked"] += 1
                self._log_gate_blocked(r, final_state, diag, gate, outcome)
                self.payment_status[r["payment_id"]] = {
                    "status": "gate_blocked",
                    "cause": diag.get("cause", "unknown"),
                    "final_outcome": "gate_blocked",
                    "amount_recovered": 0.0,
                    "action_cost": 0.0,
                    "gate_reason": gate.get("reason", "compliance violation"),
                }
                continue

            is_retryable = decision.get("is_retryable", False)

            if not is_retryable:
                counts["non_retryable"] += 1
                self._log_non_retryable(r, final_state, diag, gate, audit, outcome)
                outcome_label = _outcome_label(final_state)
                self.payment_status[r["payment_id"]] = {
                    "status": "resolved",
                    "cause": diag.get("cause", "unknown"),
                    "final_outcome": outcome_label,
                    "amount_recovered": audit.get("amount_recovered", 0.0),
                    "action_cost": audit.get("action_cost", 0.0),
                    "action_node": audit.get("action_node", "unknown"),
                }
                continue

            # Retryable payment — check gate mode
            gate_mode = gate.get("mode", "auto_approve")
            action = decision.get("action_type", "auto_retry")

            if gate_mode == "require_approval":
                counts["pending_approval"] += 1
                self.pending_actions[r["payment_id"]] = {
                    "payment_id": r["payment_id"],
                    "customer_id": r["customer_id"],
                    "amount": r["amount"],
                    "payment_method": r["payment_method"],
                    "payment_category": r["payment_category"],
                    "bank_name": r["bank_name"],
                    "failure_timestamp": r["failure_timestamp"],
                    "cause": diag.get("cause", "unknown"),
                    "confidence": diag.get("confidence", 0),
                    "recommended_action": action,
                    "original_action": gate.get("original_action", action),
                    "compliance_notes": [
                        v.get("details", "")
                        for v in gate.get("compliance_violations", [])
                    ],
                    "attempt_number": 1,
                    "is_retry": False,
                    "created_at": datetime.now().isoformat(),
                }
                self.payment_status[r["payment_id"]] = {
                    "status": "pending_approval",
                    "cause": diag.get("cause", "unknown"),
                    "final_outcome": None,
                    "amount_recovered": 0.0,
                    "action_cost": 0.0,
                    "recommended_action": action,
                }
            else:
                counts["auto_approved"] += 1
                self._schedule_retry(r, diag, decision, gate)

        # Phase 2: process auto-approved retry events
        self._run_retry_loop()

        self.logger.flush_to_json()
        return counts

    def _schedule_retry(self, record, diag, decision, gate):
        """Schedule a retryable payment's first attempt."""
        cause = diag["cause"]
        action = decision["action_type"]
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
            "downgrade_reason": None,
            "gate_mode": gate.get("mode", "auto_approve"),
            "gate_approved": True,
            "compliance_notes": compliance_notes,
            "outcome_success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "outcome_details": f"retry scheduled at {scheduled_time.isoformat()}",
            "timing_context": None,
        })

        self.payment_status[record["payment_id"]] = {
            "status": "in_progress",
            "cause": diag["cause"],
            "final_outcome": None,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
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

            self.logger.log_event({
                "payment_id": pid,
                "customer_id": r["customer_id"],
                "event_type": "retry_attempt",
                "attempt_number": result["attempt_number"],
                "sim_timestamp": scheduled_time.isoformat(),
                "action_type": payload["action_type"],
                "bandit_recommended_action": payload["action_type"],
                "actual_action": payload["action_type"],
                "downgrade_reason": None,
                "gate_mode": "auto_approve",
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
            })

            if result["status"] == "recovered":
                self._log_retryable_summary(r, self.history[pid], "recovered", scheduled_time)
                self.payment_status[pid] = {
                    "status": "resolved",
                    "cause": self.diagnosis_cache.get(pid, {}).get("cause", "unknown"),
                    "final_outcome": "recovered",
                    "amount_recovered": r["amount"],
                    "action_cost": sum(a.get("cost", 0) for a in self.history[pid]),
                }
            elif result["status"] == "escalated":
                self._log_retryable_summary(r, self.history[pid], "failed_exhausted", scheduled_time)
                self.payment_status[pid] = {
                    "status": "resolved",
                    "cause": self.diagnosis_cache.get(pid, {}).get("cause", "unknown"),
                    "final_outcome": "failed_exhausted",
                    "amount_recovered": 0.0,
                    "action_cost": sum(a.get("cost", 0) for a in self.history[pid]),
                }

    def approve_action(self, payment_id: str) -> dict:
        """Merchant approves a pending action — execute it now."""
        if payment_id not in self.pending_actions:
            return {"error": "not_found", "message": f"No pending action for {payment_id}"}

        pending = self.pending_actions.pop(payment_id)
        record = self.record_map[payment_id]
        action = pending["recommended_action"]
        cause = pending["cause"]
        attempt_number = pending["attempt_number"]
        payment_method = record["payment_method"]

        retry_time = self.clock.now()
        success = simulate_retry_outcome(cause, action, attempt_number, retry_time, self.rng)
        cost = ACTION_COSTS.get(action, 0.0)

        attempt_entry = {
            "attempt": attempt_number,
            "time": retry_time.isoformat(),
            "action": action,
            "cause": cause,
            "outcome": "success" if success else "failure",
            "cost": cost,
            "recovered": record["amount"] if success else 0.0,
        }

        if payment_id not in self.history:
            self.history[payment_id] = []
        self.history[payment_id].append(attempt_entry)

        self.logger.log_event({
            "payment_id": payment_id,
            "customer_id": record["customer_id"],
            "event_type": "approved_retry",
            "attempt_number": attempt_number,
            "sim_timestamp": retry_time.isoformat(),
            "action_type": action,
            "bandit_recommended_action": action,
            "actual_action": action,
            "downgrade_reason": None,
            "gate_mode": "require_approval",
            "gate_approved": True,
            "compliance_notes": [],
            "outcome_success": success,
            "amount_recovered": record["amount"] if success else 0.0,
            "action_cost": cost,
            "outcome_details": f"merchant-approved {action} — {'success' if success else 'failure'}",
            "timing_context": None,
        })

        if success:
            self._log_retryable_summary(record, self.history[payment_id], "recovered", retry_time)
            self.payment_status[payment_id] = {
                "status": "resolved",
                "cause": cause,
                "final_outcome": "recovered",
                "amount_recovered": record["amount"],
                "action_cost": sum(a.get("cost", 0) for a in self.history[payment_id]),
            }
            self.logger.flush_to_json()
            return {
                "payment_id": payment_id,
                "outcome": "recovered",
                "amount_recovered": record["amount"],
                "action_cost": cost,
                "attempt_number": attempt_number,
                "next_pending": None,
            }

        # Failed — check if we can retry again
        cap = max_attempts(cause)
        if attempt_number >= cap:
            self._log_retryable_summary(record, self.history[payment_id], "failed_exhausted", retry_time)
            self.payment_status[payment_id] = {
                "status": "resolved",
                "cause": cause,
                "final_outcome": "failed_exhausted",
                "amount_recovered": 0.0,
                "action_cost": sum(a.get("cost", 0) for a in self.history[payment_id]),
            }
            self.logger.flush_to_json()
            return {
                "payment_id": payment_id,
                "outcome": "failed_exhausted",
                "amount_recovered": 0.0,
                "action_cost": cost,
                "attempt_number": attempt_number,
                "next_pending": None,
            }

        # Schedule next attempt as a new pending action
        next_attempt = attempt_number + 1
        failure_time = datetime.fromisoformat(record["failure_timestamp"])
        payday_dist = retry_time.day - 1
        days_since = (retry_time - failure_time).total_seconds() / 86400

        bandit_context = {
            "original_cause": cause,
            "time_of_day": retry_time.hour,
            "day_of_week": retry_time.weekday(),
            "days_since_failure": days_since,
            "days_since_estimated_payday": payday_dist,
            "amount": record["amount"],
            "retry_attempt_number": next_attempt,
            "pre_debit_notification_sent": record.get("pre_debit_notification_sent", True),
        }
        next_action = self.bandit.select_action(bandit_context)

        from action.compliance import is_dnd
        if is_dnd(record["customer_id"]) and next_action in ("sms_then_retry", "call_then_retry"):
            next_action = "auto_retry"

        needs_approval = next_action in ("sms_then_retry", "call_then_retry", "card_update_link")

        if needs_approval:
            self.pending_actions[payment_id] = {
                "payment_id": payment_id,
                "customer_id": record["customer_id"],
                "amount": record["amount"],
                "payment_method": record["payment_method"],
                "payment_category": record["payment_category"],
                "bank_name": record["bank_name"],
                "failure_timestamp": record["failure_timestamp"],
                "cause": cause,
                "confidence": self.diagnosis_cache.get(payment_id, {}).get("confidence", 0),
                "recommended_action": next_action,
                "original_action": next_action,
                "compliance_notes": [],
                "attempt_number": next_attempt,
                "is_retry": True,
                "previous_attempts": self.history.get(payment_id, []),
                "created_at": datetime.now().isoformat(),
            }
            self.payment_status[payment_id] = {
                "status": "pending_approval",
                "cause": cause,
                "final_outcome": None,
                "amount_recovered": 0.0,
                "action_cost": sum(a.get("cost", 0) for a in self.history[payment_id]),
                "recommended_action": next_action,
            }
            self.logger.flush_to_json()
            return {
                "payment_id": payment_id,
                "outcome": "failed_retry_pending",
                "amount_recovered": 0.0,
                "action_cost": cost,
                "attempt_number": attempt_number,
                "next_pending": {
                    "attempt_number": next_attempt,
                    "recommended_action": next_action,
                },
            }
        else:
            # Auto-retry doesn't need approval — schedule it
            delay_hours = 24.0
            scheduled_time = retry_time + timedelta(hours=delay_hours)
            self.event_queue.enqueue(
                event_type="retry_attempt",
                scheduled_time=scheduled_time,
                payload={
                    "payment_id": payment_id,
                    "cause": cause,
                    "action_type": next_action,
                    "attempt_number": next_attempt,
                    "action_cost": ACTION_COSTS.get(next_action, 0.0),
                    "payment_method": payment_method,
                },
            )
            self._run_retry_loop()
            self.logger.flush_to_json()

            status = self.payment_status.get(payment_id, {})
            return {
                "payment_id": payment_id,
                "outcome": status.get("final_outcome", "in_progress"),
                "amount_recovered": status.get("amount_recovered", 0.0),
                "action_cost": cost,
                "attempt_number": attempt_number,
                "next_pending": None,
            }

    def reject_action(self, payment_id: str) -> dict:
        """Merchant rejects a pending action."""
        if payment_id not in self.pending_actions:
            return {"error": "not_found", "message": f"No pending action for {payment_id}"}

        pending = self.pending_actions.pop(payment_id)
        record = self.record_map[payment_id]

        self.logger.log_event({
            "payment_id": payment_id,
            "customer_id": record["customer_id"],
            "event_type": "merchant_rejected",
            "attempt_number": pending["attempt_number"],
            "sim_timestamp": self.clock.now().isoformat(),
            "action_type": "rejected",
            "bandit_recommended_action": pending["recommended_action"],
            "actual_action": "rejected",
            "downgrade_reason": "merchant rejected",
            "gate_mode": "require_approval",
            "gate_approved": False,
            "compliance_notes": [],
            "outcome_success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "outcome_details": "merchant rejected the recommended action",
            "timing_context": None,
        })

        self.logger.log_summary({
            "payment_id": payment_id,
            "customer_id": record["customer_id"],
            "amount": record["amount"],
            "payment_method": record["payment_method"],
            "payment_category": record["payment_category"],
            "bank_name": record["bank_name"],
            "failure_timestamp": record["failure_timestamp"],
            "failure_reason_code": record["failure_reason_code"],
            "diagnosed_cause": pending["cause"],
            "diagnosis_confidence": pending["confidence"],
            "ground_truth_cause": record["ground_truth_cause"],
            "is_retryable": True,
            "total_attempts": pending["attempt_number"] - 1,
            "final_outcome": "merchant_rejected",
            "total_amount_recovered": 0.0,
            "total_action_cost": sum(a.get("cost", 0) for a in self.history.get(payment_id, [])),
            "net_recovered": -sum(a.get("cost", 0) for a in self.history.get(payment_id, [])),
            "resolution_sim_timestamp": self.clock.now().isoformat(),
            "attempt_history": self.history.get(payment_id, []),
        })

        self.payment_status[payment_id] = {
            "status": "resolved",
            "cause": pending["cause"],
            "final_outcome": "merchant_rejected",
            "amount_recovered": 0.0,
            "action_cost": sum(a.get("cost", 0) for a in self.history.get(payment_id, [])),
        }

        self.logger.flush_to_json()
        return {"payment_id": payment_id, "outcome": "rejected"}

    def approve_all(self) -> list[dict]:
        """Approve all pending actions. Returns list of results."""
        results = []
        pids = list(self.pending_actions.keys())
        for pid in pids:
            result = self.approve_action(pid)
            results.append(result)
        return results

    def get_overview(self) -> dict:
        """Compute live overview metrics from current state."""
        if not self.batch_run:
            return {"error": "no_batch", "message": "Run batch first"}

        events = self.logger.get_all_events()
        summaries = self.logger.get_all_summaries()

        total_at_risk = sum(r["amount"] for r in self.records)

        resolved = [s for s in summaries]
        total_recovered = sum(s.get("total_amount_recovered", 0) for s in resolved)
        total_cost = sum(s.get("total_action_cost", 0) for s in resolved)
        net_recovered = total_recovered - total_cost

        # Action distribution from events
        action_counts = Counter()
        for e in events:
            at = e.get("action_type", e.get("actual_action", "unknown"))
            action_counts[at] += 1

        # Attempt distribution from summaries
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

        # Pending count
        pending_count = len(self.pending_actions)

        # Cause distribution from summaries
        cause_dist = Counter(s.get("diagnosed_cause", "unknown") for s in summaries)

        # Bank distribution with cause breakdown
        bank_stats = defaultdict(lambda: {"total": 0, "causes": Counter()})
        for s in summaries:
            bank = s.get("bank_name", "Unknown")
            bank_stats[bank]["total"] += 1
            bank_stats[bank]["causes"][s.get("diagnosed_cause", "unknown")] += 1
        bank_data = [
            {"bank": bank, "count": data["total"], "causes": dict(data["causes"])}
            for bank, data in sorted(bank_stats.items(), key=lambda x: -x[1]["total"])
        ]

        # Recovery timeline — cumulative by simulated day
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

        # Exception categories with amounts
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

        return {
            "total_payments": len(self.records),
            "total_at_risk": round(total_at_risk, 2),
            "total_recovered": round(total_recovered, 2),
            "total_cost": round(total_cost, 2),
            "net_recovered": round(net_recovered, 2),
            "recovery_rate": round(net_recovered / total_at_risk, 4) if total_at_risk > 0 else 0,
            "resolved_count": len(summaries),
            "pending_count": pending_count,
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
        }

    def get_pending(self) -> list[dict]:
        """Return pending actions sorted by amount descending."""
        pending = list(self.pending_actions.values())
        pending.sort(key=lambda p: p["amount"], reverse=True)
        return pending

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
        """Return detail view for a single payment including timeline."""
        if payment_id not in self.record_map:
            return None

        r = self.record_map[payment_id]
        ps = self.payment_status.get(payment_id, {})
        diag = self.diagnosis_cache.get(payment_id, {})
        events = self.logger.get_payment_events(payment_id)
        summary = self.logger.get_payment_summary(payment_id)
        pending = self.pending_actions.get(payment_id)

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
            "pending_action": pending,
        }

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
