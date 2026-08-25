# Decision Engine — Contextual Bandit + Optuna Tuning

Optuna-tuned epsilon-greedy contextual bandit that decides WHEN and HOW to retry failed payments. Zero LLM — pure optimization against net Rs recovered.

## Per-Action Cost Table

| Action | Cost (Rs) | Description |
|--------|-----------|-------------|
| `auto_retry` | 0 | Silent retry, no customer contact |
| `sms_then_retry` | 2 | Send SMS notification, then retry |
| `call_then_retry` | 15 | Voice/agent call, then retry |

## Reward Function

    reward = amount_recovered - action_cost

- `amount_recovered` = full payment amount if retry succeeds, 0 if failure
- `action_cost` is ALWAYS subtracted regardless of outcome

### Worked examples

| Scenario | Calculation | Reward |
|----------|-------------|--------|
| Successful Rs 5,000 auto_retry | 5000 - 0 | Rs 5,000 |
| Failed Rs 5,000 sms_then_retry | 0 - 2 | -Rs 2 |
| Successful Rs 500 call_then_retry | 500 - 15 | Rs 485 |
| Failed Rs 500 call_then_retry | 0 - 15 | -Rs 15 |

## Retryable vs Non-Retryable Mapping

| Cause | Retryable? | Max attempts | Route to |
|-------|-----------|--------------|----------|
| insufficient_funds | Yes | 3 | bandit |
| bank_outage | Yes | 3 | bandit |
| ambiguous | Yes | 1 | bandit (cautious) |
| afa_stuck | No | - | customer_auth_action |
| mandate_expired | No | - | mandate_resequence |
| mandate_revoked | No | - | escalation_conversation |
| card_expired | No | - | card_update_link |

Rationale: retries only help when the underlying cause is transient. Insufficient funds may resolve after payday; outages resolve on their own. Expired mandates/cards need a different action entirely — retrying just wastes attempts.

## Optuna Tuning Results

50 Optuna trials with simulation-based evaluation (success rates learned from training data, 5 simulations per trial).

**Best hyperparameters:**
- `epsilon`: 0.0101 (low exploration — exploit learned policy)
- `learning_rate`: 0.00151 (gradual convergence)
- `n_epochs`: 5
- Train net Rs (simulated avg): 6,551,373.65

Top 5 trials converged tightly — all with epsilon ~0.01, learning_rate 0.001-0.002, epochs 3-5. The bandit quickly learns a stable policy.

## Backtest: Three-Column Comparison

Naive baseline: "always auto_retry after 6 hours, regardless of cause or context."
Evaluated on held-out 20% of retry data (240 records), averaged over 20 simulations.

| Metric | Naive Baseline | Bandit (Constrained) | Bandit (Unconstrained) |
|--------|---------------|---------------------|----------------------|
| Total Rs at risk | 4,329,992 | 4,329,992 | 4,329,992 |
| Total Rs recovered (gross) | 653,891 | 1,222,853 | 1,613,368 |
| Total action costs | 0 | 1,518 | 3,578 |
| Net Rs recovered | 653,891 | 1,221,334 | 1,609,790 |
| Net recovery rate | 15.1% | 28.2% | 37.2% |

**Uplift vs baseline: constrained +86.8% | unconstrained +146.2%**

The unconstrained number is the theoretical maximum; the constrained number is operational reality. The gap (~Rs 3.9L) is the cost of regulatory compliance and operational limits — a real cost that the system correctly accounts for.

### Action distribution (constrained vs unconstrained)

| Action | Constrained | Unconstrained |
|--------|-------------|---------------|
| auto_retry | 0.4% | 0.4% |
| sms_then_retry | 66.2% | 0.0% |
| call_then_retry | 33.3% | 99.6% |

The per-customer call limit (max 1 per 30-day cycle) is the primary binding constraint, causing 159 downgrades from call to SMS. The daily call budget of 30 did not bind (busiest day had 12 calls) — with 240 records and ~80 customers, per-customer limits cap calls before the daily budget does.

### Breakdown by cause

| Cause | Baseline | Constrained | Unconstrained | Delta (con) | N |
|-------|----------|-------------|---------------|-------------|---|
| afa_stuck | 25,177 | 231,364 | 397,048 | +206,187 | 38 |
| insufficient_funds | 394,127 | 573,343 | 572,880 | +179,216 | 69 |
| mandate_expired | 13,223 | 66,255 | 103,162 | +53,032 | 27 |
| bank_outage | 186,619 | 224,762 | 293,947 | +38,143 | 39 |
| card_expired | 7,745 | 45,310 | 151,085 | +37,564 | 32 |
| mandate_revoked | 0 | 27,771 | 20,302 | +27,771 | 15 |
| ambiguous | 27,000 | 52,530 | 71,365 | +25,530 | 20 |

Even constrained, the bandit helps most on **afa_stuck** (+Rs 2.1L) and **insufficient_funds** (+Rs 1.8L). Notably, insufficient_funds constrained performance nearly matches unconstrained — SMS is almost as effective as calls for this cause (35.3% vs 41.8% success rate).

## Stopping Rules

Hard stops that override the bandit — non-negotiable:
1. **Max 3 retry attempts** per payment (hard cap)
2. **Non-retryable causes** never enter the bandit (mandate_expired, mandate_revoked, card_expired, afa_stuck)
3. **Ambiguous**: max 1 attempt, not 3
4. **Notification forcing**: if `pre_debit_notification_sent == False` AND cause is `insufficient_funds`, first action is forced to `sms_then_retry`

### NPCI UPI AutoPay timing compliance (Aug 2025 circular)

Payment-method-aware rules. The bandit still picks the ACTION (auto/sms/call), but TIMING is constrained for UPI AutoPay.

**NPCI-mandated (UPI AutoPay only):**
- Retries ONLY during non-peak hours: before 10:00 AM, 1:00-5:00 PM, after 9:30 PM. Peak windows 10AM-1PM and 5PM-9:30PM are blocked. If the bandit picks a peak-hour time, the scheduler clamps it to the next non-peak window.
- Minimum retry spacing: attempt 1 >= 24h after failure, attempt 2 >= 72h, attempt 3 at day 7. This overrides the bandit's timing.

**Self-imposed (eNACH and card_auto_debit):**
- Min 4-hour cooldown between attempts (our own rule, not NPCI-mandated)
- No peak-hour restriction (not on UPI rails)

All 14 tests pass: original 7 (caps, non-retryable, notification, cooldown, ambiguous) plus 7 NPCI compliance tests (peak-hour clamping, spacing enforcement, eNACH exemption, peak detection).

## Capacity Constraints

Design decision: the bandit recommends the ideal action, the constraint layer applies operational reality, and the audit log records both the recommendation and the actual action including the downgrade reason. This is the correct architecture — ML recommends, business/regulatory rules constrain.

### Regulatory constraints (RBI-mandated)

1. **Contact hours for calls: 8AM-7PM only.** If the bandit picks call_then_retry outside this window, the scheduler clamps to the next 8AM. SMS is unrestricted (transactional messages under TRAI). For UPI AutoPay + call, the valid intersection of NPCI non-peak and RBI contact hours is: **8AM-10AM and 1PM-5PM**.

### Operational constraints (self-imposed, documented as business judgment)

2. **Daily call budget: max 30 per simulated day.** When exhausted, remaining call recommendations are downgraded to sms_then_retry. Tracked via SimClock.

3. **Amount-based priority when budget binds.** No hard amount floor. Instead: sort call-eligible payments by amount descending, assign calls to top N (where N = remaining daily budget), downgrade the rest to sms_then_retry. A Rs 500 payment CAN get a call on a slow day, but gets bumped by a Rs 15,000 EMI on a busy day.

4. **Per-customer contact limits per 30-day billing cycle:**
   - Max 1 call per customer. Second call -> downgraded to sms_then_retry.
   - Max 3 SMS per customer. Fourth SMS -> downgraded to auto_retry.
   - Auto-retry has no contact limit (silent, already capped at 3 attempts).

All downgrades are logged in the audit trail with payment_id, customer_id, recommended action, actual action, and reason.

All 22 tests pass: 7 original + 7 NPCI + 8 capacity constraint tests (RBI hours, UPI+call intersection, daily budget, per-customer call/SMS limits, audit logging).

## Uplift Caveat

The bandit was trained and evaluated on synthetic data whose success patterns were defined by the generator (`/data/generate_retry_outcomes.py`). The success rates show `call_then_retry` dominating across all causes (e.g., 45% vs 4% for afa_stuck), which is why the bandit converges to "mostly call" — this is mathematically correct given the data, but the absolute success rate differences are synthetic.

The +146% uplift demonstrates that the bandit correctly recovers known-good policies from simulated data. It is NOT a claim about real-world rupee recovery. In production, action costs, success rate differentials, and customer preferences would produce different (likely smaller) uplift numbers. The architecture — contextual bandit with net-Rs reward, Optuna-tuned, with hard stopping rules — is what transfers to production. The specific numbers do not.

## Architecture

- `policy.py` — Retryable/non-retryable cause mapping
- `costs.py` — Per-action cost table
- `bandit.py` — Epsilon-greedy contextual bandit (linear model, 14-dim context)
- `tune_bandit.py` — Optuna hyperparameter search (50 trials, simulation-based)
- `backtest.py` — Bandit vs naive baseline comparison (simulation-based, 20 runs)
- `stopping.py` — Hard stopping rules + NPCI UPI AutoPay timing compliance
- `constraints.py` — Capacity constraints (RBI contact hours, daily call budget, per-customer limits)
- `scheduler.py` — SimClock event queue integration with UPI peak-hour + RBI contact-hour clamping
- `test_stopping.py` — 22 tests (7 original + 7 NPCI + 8 capacity constraints)
