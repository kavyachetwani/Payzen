# /audit — Firestore Audit Logging + Metrics

Full audit trail stored in Firestore (or local JSON fallback). Every action 
taken by the system is logged, and three reporting scripts produce financial 
metrics, exception lists, and headline summaries.

## Two-Collection Schema

### Why two collections?

- **audit_events** — granular per-attempt history. One document per action 
  taken. A payment retried 3 times produces 3 event documents. Supports 
  streaming analytics and real-time dashboards via Firestore listeners in 
  production.
- **audit_summary** — quick per-payment querying. One document per payment 
  with the final resolved state plus denormalized attempt history. Used by 
  metrics and exception scripts.

### audit_events (one doc per action)

| Field | Type | Description |
|-------|------|-------------|
| event_id | str | Auto-generated UUID |
| payment_id | str | Payment reference |
| customer_id | str | Customer reference |
| event_type | str | initial_processing / retry_attempt / escalation_after_exhaustion |
| attempt_number | int | 0 for scheduling, 1-3 for retry attempts |
| sim_timestamp | str | SimClock time when this event executed |
| action_type | str | auto_retry / sms_then_retry / call_then_retry / card_update_link / mandate_resequence / escalation / gate_blocked / scheduled |
| bandit_recommended_action | str? | What the bandit chose (before constraints) |
| actual_action | str | After constraints/gate — may differ |
| downgrade_reason | str? | Why the action was changed |
| gate_mode | str | auto_approve / require_approval / reject |
| gate_approved | bool | Whether the gate allowed the action |
| compliance_notes | list[str] | Any compliance check details |
| outcome_success | bool | Whether this attempt recovered money |
| amount_recovered | float | ₹ recovered (0 if failed) |
| action_cost | float | ₹ cost of this action |
| outcome_details | str | Human-readable outcome |
| timing_context | dict? | days_since_failure, days_since_payday, time_of_day |
| logged_at | str | Real wall-clock time |

### audit_summary (one doc per payment)

| Field | Type | Description |
|-------|------|-------------|
| payment_id | str | Document ID |
| customer_id | str | Customer reference |
| amount | float | Original payment amount |
| payment_method | str | upi_autopay / enach / card_auto_debit |
| payment_category | str | subscription / emi / sip / insurance / cc_bill |
| bank_name | str | Bank name |
| failure_timestamp | str | Original failure time |
| failure_reason_code | str | NACH return code |
| diagnosed_cause | str | What the diagnosis engine determined |
| diagnosis_confidence | float | Confidence score (0.30-0.95) |
| ground_truth_cause | str | Eval only — would not exist in production |
| is_retryable | bool | Whether the cause is retryable |
| total_attempts | int | Number of retry attempts made |
| final_outcome | str | recovered / failed_exhausted / escalated / card_update_sent / mandate_resequenced / gate_blocked |
| total_amount_recovered | float | Sum across all attempts |
| total_action_cost | float | Sum across all attempts |
| net_recovered | float | Recovered minus costs |
| resolution_sim_timestamp | str | When the payment was finally resolved |
| attempt_history | list[dict] | Denormalized attempt summaries |
| logged_at | str | Real wall-clock time |

## Running the Scripts

### Generate audit data

```bash
python action/run_batch_multi.py
```

This processes all 500 payments through the multi-attempt pipeline and writes 
audit data to Firestore (or fallback JSON files).

### Financial metrics

```bash
python audit/metrics.py
```

11 sections: headline financials, by cause, by outcome, by action type, 
attempt distribution, constraint impact, single-pass vs multi-attempt.

### Exception list

```bash
python audit/exceptions.py
```

Categorized unrecovered payments: exhausted retries, gate-blocked, escalated, 
pending non-retryable. Includes ₹ at-risk totals and suggested next steps.

### Combined headline summary

```bash
python audit/summary.py
```

One-page output for demo/video: diagnosis accuracy, bandit uplift, 
multi-attempt uplift, recovery rate, attempt distribution, compliance stats.

## Fallback Behavior

If Firestore credentials are unavailable (no `GOOGLE_APPLICATION_CREDENTIALS` 
environment variable), the logger automatically falls back to writing two 
local JSON files:

- `audit/audit_events_fallback.json`
- `audit/audit_summary_fallback.json`

All reporting scripts read from these fallback files. A warning is printed 
but the batch never crashes.

## Production Notes

In production, audit_events would also support streaming analytics and 
real-time dashboards via Firestore listeners. The two-collection design 
separates the write-heavy event stream from the queryable summary layer, 
keeping reads fast even as event volume grows.
