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

## Final Test Results

```
69 passed, 0 failed, 1 warning in 5.34s
```

All 7 test files, 69 tests, passing green.
