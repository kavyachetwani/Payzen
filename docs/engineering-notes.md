# Stage 9 — Backbone Hardening: Engineering Notes

## Test Suites Written

| # | File | Tests | Scope |
|---|------|-------|-------|
| 1A | `tests/test_consistency.py` | 8 | Pipeline consistency: outcome sums, no duplicates, event-summary linkage |
| 1B | `tests/test_financials.py` | 8 | Financial math: net = recovered - cost, no NaN/Inf, no over-recovery |
| 1C | `tests/test_diagnosis_integrity.py` | 6 | Diagnosis accuracy: >93%, known causes, confidence in (0,1] |
| 2 | `tests/test_adversarial.py` | 18 | Edge cases: zero amount, missing fields, unknown codes, DND, budget caps |
| 3 | `tests/test_stopping_stress.py` | 14 | Stopping rules: max retries, contact limits, DND, RBI hours, NPCI timing |
| 4 | `tests/test_api.py` | 9 | PipelineServer: approval flow, double-batch idempotency, overview integrity |
| 5 | `tests/test_dashboard_data.py` | 6 | Dashboard data shape: required fields, null checks, known outcomes |
| **Total** | | **69** | |

## Bugs Found and Fixed

### Bug 1: `build_db` function missing from `diagnosis/db.py`

**What broke:** All 20 tests in `test_diagnosis_integrity.py` (6) and `test_adversarial.py` (14) failed with `ImportError: cannot import name 'build_db' from 'diagnosis.db'`.

**Why:** The tests were written to call `build_db(records)` to create an in-memory SQLite DB from a list of dicts, but the module only had `init_db(db_path, data_path)` which reads from a file path.

**Fix:** Added `build_db(records, db_path=":memory:")` and a `_load_records()` helper to `diagnosis/db.py` that populates the schema from a list of dicts with `.get()` defaults for all fields.

**Commit:** `bug: tests reference nonexistent build_db, fallback JSON incomplete (221/500)` → `fix: enforce constraints across phases, add build_db for test isolation`

---

### Bug 2: Constraint tracker not enforcing across pipeline phases

**What broke:** 3 stopping-stress tests failed:
- `test_max_1_call_per_customer`: CUST_00314 received 2 calls (from 2 different payments)
- `test_max_3_sms_per_customer`: CUST_00348 received 5 SMS (from 3 different payments)
- `test_dnd_customers_no_contact`: CUST_00176 (DND) received `sms_then_retry`

**Root cause (3 sub-bugs):**

1. **Phase 1 skipped ConstraintTracker:** When scheduling initial retry actions in `run_batch_multi.py`, the action from the LangGraph decision was used directly. `constraint_tracker.apply_constraints()` was never called, so Phase 1 contacts were invisible to Phase 2.

2. **DND not checked in Phase 1 scheduling:** The `dnd_set` was computed but never checked before scheduling contact actions for retryable payments.

3. **Current retry action not recorded in tracker:** In `process_retry_event`, only the *next* scheduled action went through `apply_constraints()`. The *current* action (from the queue payload) was executed without recording it, so the tracker's sliding-window counters missed it.

4. **Audit logged original action, not constrained action:** `run_batch_multi.py` logged `payload["action_type"]` (the pre-constraint action) instead of the actual executed action, so even after constraint fixes, the logged events would show the wrong action.

**Fix:**
- Added DND check before scheduling in Phase 1 (`run_batch_multi.py:240-241`)
- Added `constraint_tracker.apply_constraints()` call in Phase 1 (`run_batch_multi.py:263-266`)
- Added DND recheck + `apply_constraints()` for the current action in `process_retry_event` (`retry_processor.py:100-107`)
- Added `actual_action` to all return dicts from `process_retry_event`
- Updated audit event logging to use `result["actual_action"]` instead of `payload["action_type"]`

**Commit:** `bug: constraint tracker not enforcing across phases` → `fix: enforce constraints across phases, add build_db for test isolation`

---

### Bug 3: Fallback JSON overwritten by test_api.py

**What broke:** `test_consistency.py` and `test_dashboard_data.py` saw only 221/222 summaries instead of 500, because `test_api.py` (which runs first alphabetically) creates its own `PipelineServer` whose `AuditLogger.flush_to_json()` overwrites the shared fallback JSON files.

**Fix:**
- Changed `conftest.py` to read fallback JSON files eagerly at module level (import time) instead of lazily in fixtures
- Patched `AuditLogger.flush_to_json` to a no-op in `test_api.py`'s module-scoped fixture

## Bug #2 — Constraint tracker blind to Phase 1 contacts (Stage 9)

**Impact:** per-customer contact limits silently violated — one customer got 2 calls (max 1), another got 5 SMS (max 3), a DND customer got an SMS

**What happened:**

The retry pipeline has two phases. Phase 1 processes all 500 payments through the LangGraph graph, classifies them as retryable or non-retryable, and schedules first retry attempts into the SimClock event queue. Phase 2 pops events from the queue and executes them — simulate the retry, log the outcome, schedule the next attempt if needed.

The `ConstraintTracker` enforces operational limits: max 1 call per customer per 30-day cycle, max 3 SMS per cycle, daily call budget of 30. It works by recording each contact in a sliding-window counter when `apply_constraints()` is called. The problem was where it got called.

In Phase 2, `process_retry_event()` called `apply_constraints()` — but only when scheduling the *next* attempt. The current attempt's action came from the queue payload, already decided, and was executed directly without going through the tracker. And in Phase 1, the tracker was never called at all. The graph's internal compliance node ran, but it's a separate system — it flags violations for the audit log but doesn't feed into the ConstraintTracker's counters.

So the tracker was always one step behind, and completely blind to Phase 1.

**How I found it:**

Three stopping-stress tests failed on first run:
- `test_max_1_call_per_customer`: CUST_00314 had 2 call events — PAY_00029 (attempt 1, scheduled in Phase 1) and PAY_00137 (attempt 2, scheduled in Phase 2). The Phase 1 call was invisible to the tracker, so when Phase 2 scheduled PAY_00137's call, the tracker saw zero prior calls for CUST_00314 and let it through.
- `test_max_3_sms_per_customer`: CUST_00348 had 5 SMS events across 3 different payments (PAY_00118, PAY_00371, PAY_00255 with 3 attempts). Same root cause — initial SMS contacts from Phase 1 never recorded.
- `test_dnd_customers_no_contact`: CUST_00176 is in the DND opt-out set (seeded with `np.random.RandomState(99)`, 13 of 277 customers). PAY_00049 got scheduled with `sms_then_retry` in Phase 1. The `dnd_set` was computed but never checked before scheduling.

I queried the audit events for each customer, saw contacts from multiple payments, and traced the scheduling path back to `run_batch_multi.py` Phase 1 — no `apply_constraints()` call anywhere in that block.

**Fix:**

Three changes:

1. Added DND check in Phase 1 before scheduling (`run_batch_multi.py`): `if customer_id in dnd_set and action in ("sms_then_retry", "call_then_retry"): action = "auto_retry"`. Same pattern that already existed in `process_retry_event` for the next action, just applied to the initial action too.

2. Added `constraint_tracker.apply_constraints(action, customer_id, scheduled_time, payment_id)` in Phase 1 after deciding the action. This records the contact in the tracker so Phase 2 sees it.

3. Added DND recheck + `apply_constraints()` at the top of `process_retry_event()` for the *current* action before executing it. Previously only the next scheduled action went through constraints; now the current one does too.

**Takeaway:** If you have a stateful enforcement layer (the ConstraintTracker), every code path that takes the enforced action needs to go through it. Having it in one phase but not the other is worse than not having it at all — it creates false confidence that limits are being respected.

---

## Bug #3 — Audit trail logged pre-constraint action (Stage 9)

**Impact:** audit events showed contact actions that didn't actually happen — phantom calls and SMS in the compliance log

**What happened:**

This one fell out of fixing Bug #2. After adding constraint enforcement to both phases, the actual executed action could now differ from the originally scheduled action. For example, the bandit recommends `call_then_retry`, but at execution time the tracker sees the customer already had a call this cycle and downgrades to `sms_then_retry` (or `auto_retry` if SMS is also exhausted).

But `run_batch_multi.py` logged the event like this:

```python
logger.log_event({
    "action_type": payload["action_type"],       # from queue — pre-constraint
    "actual_action": payload["action_type"],      # same thing
    "downgrade_reason": None,
})
```

It used `payload["action_type"]` — the action as originally scheduled in the queue, before any constraint checking. So even after the fix, the audit trail would show `call_then_retry` for an action that actually executed as `auto_retry`. The stopping-stress tests count actual logged events, so they'd still see violations that don't exist in reality.

**How I found it:**

After fixing constraint enforcement, the constraint tests still failed intermittently — the tracker was correctly downgrading actions, but the logged events didn't reflect it. Traced the audit event construction in `run_batch_multi.py` and saw it was pulling from the raw payload, not from the `process_retry_event` result.

**Fix:**

Added `actual_action` field to all three return paths in `process_retry_event()` (recovered, escalated, scheduled_next). Updated the caller in `run_batch_multi.py` to use `result["actual_action"]` instead of `payload["action_type"]`, and set `downgrade_reason` to `"constraint_downgrade"` when they differ.

**Takeaway:** Constraint enforcement and audit logging need to read from the same source of truth. If enforcement happens inside a function but the caller logs the pre-enforcement input, your audit trail contradicts your actual behavior — which is exactly the kind of discrepancy a compliance audit would flag.

---

## Final Test Results

```
69 passed, 0 failed, 1 warning in 5.34s
```

All 7 test files, 69 tests, passing green.
