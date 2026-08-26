# Compliance Framework

Plain-language explanation of every compliance check the pipeline enforces, why it exists, and what happens when it fires.

## How It Works

An approval gate sits between the decision engine and the action nodes. Every payment flows through four compliance checks before any customer-facing action executes. If any check fails, the gate either modifies the action (downgrade, force) or blocks it entirely.

### Gate Modes

| Mode | Meaning | When |
|------|---------|------|
| **auto_approve** | Action proceeds without review | Silent retries, mandate resequence, escalations |
| **require_approval** | Action needs human approval (auto-approved in batch mode) | SMS, calls, card update links |
| **reject** | Action blocked — compliance violation | DND customer + no contactless fallback |

## The Four Checks

### 1. DND Opt-Out

**What**: ~5% of customers are flagged as DND (Do Not Disturb) opt-outs. If a customer is DND, we cannot send them an SMS or call them.

**Why**: TRAI regulations. Contacting DND-registered customers without consent is a legal violation.

**What happens**:
- If the planned action is SMS/call and the customer is DND:
  - **Retryable payment** → downgrade to silent auto_retry (no customer contact)
  - **Non-retryable payment** (e.g., card expired, needs update link) → **block entirely**. No contactless fallback exists, so the pipeline records "no action possible" and moves on.

**Batch results**: 22 DND triggers — 19 downgraded to auto_retry, 3 blocked (card_expired customers with no contactless option).

### 2. Pre-Debit Notification

**What**: RBI mandates that customers receive a pre-debit notification before a recurring payment is attempted. If the `pre_debit_notification_sent` field is `false` and this is the first retry attempt, the pipeline forces the action to `sms_then_retry` so the customer gets notified before the retry.

**Why**: RBI circular on e-mandate framework (2019, updated 2021). Without notification, the debit may be disputed and reversed.

**What happens**:
- First retry + no notification sent → force `sms_then_retry` regardless of what the bandit chose
- Second+ retry → notification requirement satisfied by the first forced SMS, allow any action

**Batch results**: 5 payments forced to `sms_then_retry` due to missing pre-debit notification.

### 3. Contact Hours Safety Net

**What**: RBI prohibits customer contact outside 8:00 AM – 7:00 PM. The constraint layer (Stage 4.2) already enforces this at scheduling time. This check is a redundant safety net.

**Why**: Defense in depth. If the scheduling layer has a bug, the gate catches it before the action executes.

**What happens**: If a contact action (SMS/call) is about to execute outside RBI hours → block.

**Batch results**: 0 violations. The scheduling layer correctly prevents out-of-hours actions.

### 4. Contact Limits Safety Net

**What**: Per-customer contact limits — max 1 call and 3 SMS per 30-day cycle. Again, the constraint layer already enforces this. This check is a redundant safety net.

**Why**: Same defense-in-depth principle. Over-contacting a customer is both a compliance risk and a churn risk.

**What happens**: If a customer has already hit their call/SMS limit for the cycle → block.

**Batch results**: 0 violations. The constraint layer correctly tracks and enforces per-customer limits.

## Graph Flow

```
START → diagnose → decide → gate → [router] → action node → END
                              ↓
                          (if rejected)
                              ↓
                             END
```

Blocked payments get:
- `action_outcome.success = false`
- `action_outcome.amount_recovered = 0`
- `action_outcome.details = "blocked by gate — reason: <reason>"`
- Full audit trail with `action_node = "gate_blocked"`

## Summary Table

| Check | Source Regulation | Catch Rate | Safety Net? |
|-------|------------------|------------|-------------|
| DND opt-out | TRAI DND registry | 4.4% of payments | Primary — no upstream enforcement |
| Pre-debit notification | RBI e-mandate circular | 1.0% of payments | Primary — forces SMS before retry |
| Contact hours | RBI fair practice code | 0% (caught upstream) | Yes — Stage 4.2 handles it |
| Contact limits | RBI fair practice code | 0% (caught upstream) | Yes — Stage 4.2 handles it |
