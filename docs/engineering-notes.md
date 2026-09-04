# Technical (for /docs/engineering-notes.md)

## Bug: Constraint tracker blind to Phase 1 scheduling + audit trail logging wrong action

**Impact:** 3 compliance violations across 500 payments. CUST_00314: 2 calls (max 1). CUST_00348: 5 SMS (max 3). CUST_00176: 1 SMS to a DND-registered customer.

### How I found it

I was running the Stage 9 hardening tests. 69 tests across 7 suites. consistency checks, financial math, adversarial inputs, stopping rule stress tests, API tests, dashboard data integrity.

Test `test_no_over_contact` in `test_stopping_stress.py` does something none of the unit tests do: it loads every audit event for the entire 500-payment batch, groups by customer_id, and sums total calls and total SMS per customer across ALL their payments and ALL retry attempts. Then it asserts no customer exceeds the limits.

It failed on 3 customers. I printed the offending events:

```
CUST_00314:
  PAY_00029, attempt 1. call_then_retry (Phase 1 scheduled)
  PAY_00137, attempt 2. call_then_retry (Phase 2 executed)
  Total calls: 2. Max allowed: 1.

CUST_00176 (DND):
  PAY_00097, attempt 1. sms_then_retry (Phase 1 scheduled)
  Should have been blocked entirely.
```

### Root cause analysis

The pipeline runs in two phases:

* Phase 1 (`run_batch_multi.py`): processes all 500 payments through the LangGraph graph (diagnose, decide, gate), then for retryable payments, creates SimClock events in the queue with the bandit's chosen action.
* Phase 2 (`retry_processor.py`): the SimClock driver pops events chronologically and executes each retry.

The `ConstraintTracker` was initialized at batch start and passed to Phase 2. Phase 2 called `apply_constraints()` before executing each retry and before scheduling the NEXT retry. But Phase 1 never called the tracker at all.

So when Phase 1 scheduled `call_then_retry` for PAY_00029 (CUST_00314), the tracker didn't record it. When Phase 2 later processed PAY_00137 (same customer, different payment), the tracker thought this was the customer's FIRST call — because it never saw the one Phase 1 scheduled. So it allowed a second call.

For DND: Phase 1 computed the `dnd_set` (13 customers, 4.7%) but never checked it before scheduling customer-facing actions. The graph's internal compliance node flagged it, but the gate check happened after the action was already queued — the wrong order.

### First fix (constraint enforcement)

Three changes:

1. `run_batch_multi.py`, Phase 1 scheduling block: added `if customer_id in dnd_set and action in ("sms_then_retry", "call_then_retry"): action = "auto_retry"` before enqueuing.
2. `run_batch_multi.py`, Phase 1 scheduling block: added `constraint_tracker.apply_constraints(action, customer_id, scheduled_time, payment_id)` so the tracker records the initial contact.
3. `retry_processor.py`, `process_retry_event()`: added DND recheck and `apply_constraints()` call for the CURRENT action before executing it, not just when scheduling the next one.

After this fix: re-ran the stress tests. All contact-limit tests passed. 0 violations.

### Then I found the second bug

While verifying the fix, I checked the audit events for CUST_00314 to confirm the logged actions matched reality. They didn't. The audit trail showed `call_then_retry` for an action that had been downgraded to `sms_then_retry` by the constraint layer.

The audit logger in `run_batch_multi.py` wrote `payload["action_type"]` — the action as originally enqueued by Phase 1. But after the first fix, `process_retry_event()` now downgrades actions at execution time (e.g., call → SMS if customer already had a call). The audit event still recorded the original action, not the downgraded one.

So the system was now correctly enforcing constraints but incorrectly logging what it did. The audit trail showed phantom contacts that didn't happen.

### Second fix (audit accuracy)

Added `actual_action` field to all return dicts from `process_retry_event()`. Changed the audit logging line from `payload["action_type"]` to `result["actual_action"]`. Also added `downgrade_reason` to the audit event when an action was changed.

### Verification

Re-ran all 69 tests. All passed. Manually inspected CUST_00314's audit trail — now correctly shows the downgrade from call to SMS with reason "customer already called 1x this cycle (max 1)".

### Takeaway

Unit tests tested each phase in isolation. Each phase worked correctly on its own. The bug only appeared when both phases ran together on a full batch where customers had multiple payments. The constraint tracker was correct — it just wasn't being called in the right places. The audit trail was correct — it just read from the wrong variable.

The test that caught this wasn't clever — it just did something obvious (sum contacts per customer across the whole batch) that none of the unit tests bothered to do because they tested one payment at a time.
