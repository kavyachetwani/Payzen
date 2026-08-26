# LangGraph Action Router

LangGraph pipeline that wires diagnosis (Stage 3) and decision (Stage 4) together with action nodes that execute recovery actions.

## Graph Structure

```
START → diagnose → decide → [router]
                              ├─ retry       → END   (retryable causes)
                              ├─ card_update → END   (card_expired)
                              ├─ resequence  → END   (mandate_expired)
                              └─ escalate    → END   (mandate_revoked, low confidence)
```

## Nodes

1. **diagnose** — Calls the SQL-based diagnosis engine from Stage 3. Writes `state.diagnosis = {cause, confidence}`.

2. **decide** — Runs through: retryable/non-retryable mapping → bandit (if retryable) → stopping rules → capacity constraints. Writes `state.decision` and `state.constraint_result`.

3. **retry** — Simulates retry for retryable causes (auto/sms/call). Uses learned success rates from the bandit's training data to probabilistically determine success/failure. For sms_then_retry, logs SMS sent first. For call_then_retry, logs call made first.

4. **card_update** — For card_expired. Sends card-update link via SMS. No recovery claimed in this cycle (customer must update card for next billing to succeed).

5. **resequence** — For mandate_expired. Initiates mandate re-registration. No recovery claimed in this cycle.

6. **escalate** — For mandate_revoked, low-confidence diagnoses (confidence < 0.5, excluding ambiguous), and exhausted retries. Adds to human-review queue.

## Router Logic

- `is_retryable == True` → retry
- `route_to == "card_update_link"` → card_update
- `route_to == "mandate_resequence"` → resequence
- `route_to == "escalation"` or `"escalation_conversation"` → escalate
- `confidence < 0.5` (non-ambiguous) → escalate (override)

Note: ambiguous cause has confidence 0.30, but this is the expected confidence for "genuinely ambiguous" — it's not uncertainty about the diagnosis. The low-confidence escalation override applies only to non-ambiguous causes where 0.30-0.50 would indicate diagnostic uncertainty.

## Batch Results (500 records)

### Action Node Distribution

| Node | Count | % |
|------|-------|---|
| retry | 299 | 59.8% |
| card_update | 60 | 12.0% |
| resequence | 50 | 10.0% |
| escalate | 91 | 18.2% |

### Financial Summary

| Metric | Value |
|--------|-------|
| Total Rs at risk | 16,466,953 |
| Total Rs recovered | 2,081,780 |
| Total action costs | 1,100 |
| Net Rs recovered | 2,080,680 |
| Recovery rate | 12.6% |

### Recovery by Cause

| Cause | Count | Net Recovered |
|-------|-------|---------------|
| insufficient_funds | 159 | 936,999 |
| bank_outage | 95 | 864,784 |
| ambiguous | 45 | 279,018 |
| afa_stuck | 66 | 0 (escalated) |
| card_expired | 60 | -120 (link cost) |
| mandate_expired | 50 | 0 (resequenced) |
| mandate_revoked | 25 | 0 (escalated) |

## How Mock Outcomes Work

Success rates are learned from the retry outcome training data (`/data/retry_outcomes.json`) as P(success | cause, action_type). The same RNG seed (42) ensures deterministic outcomes across runs.

## Extensibility

The graph is designed to be extended, not rebuilt:
- Stage 6: human-in-the-loop gate inserts between decide and the router
- Stage 7: Firestore audit logging plugs into the audit_entry dict already accumulated in state
- Stage 11: Hinglish voice/text node plugs into the escalation path

## Architecture

- `state.py` — TypedDict state schema
- `nodes.py` — Node functions (diagnosis, decision, retry, card update, resequence, escalation)
- `router.py` — Conditional edge function
- `graph.py` — Graph assembly and compilation
- `run_batch.py` — Batch runner with summary stats and sample traces
