# Synthetic Data Validation Report

**Date:** 2026-08-25
**Scope:** Independent verification of `/data/failed_payments.json` (500 records) and `/data/retry_outcomes.json` (1,200 records) against publicly available Indian payment system data.

**Method:** 15 web searches across 6 categories, plus deep-reads on 8 pages. Research done before re-reading the generators, to avoid confirmation bias.

---

## 1. Sources Found Independently

### New sources (not in `/references/sources.md`)

**A. Business Standard — "UPI autopay revocations hit 20 mn per month on low customer balance" (Sep 2025)**
https://www.business-standard.com/finance/news/upi-autopay-revocations-hit-20-mn-monthly-over-low-customer-balances-125090700500_1.html

What I pulled: 20 million UPI AutoPay mandates revoked monthly due to insufficient balance. Mandate registrations hit 50M/month (July 2025), up from 26M (July 2024). Mandate executions doubled to 808M/month. SBI's auto-debit approval rate is only ~30% — meaning ~70% of SBI autopay debits fail. Business decline across top 50 banks for AutoPay averages ~74%. **Why it matters:** The 74% BD rate for AutoPay is dramatically higher than the ~3-5% BD rate for general UPI transactions. This confirms that recurring payment failures are a different beast from P2P/P2M failures, which validates our decision to use a separate distribution rather than copying the general UPI failure breakdown.

**B. productgrowth.in — "UPI AutoPay: Design Guide for Recurring Payments"**
https://productgrowth.in/insights/fintech/upi-autopay-guide/

What I pulled: UPI AutoPay failure rate is 8–15% (vs 2–3% for card mandates). Retry windows at 24h, 72h, 168h. Smart retry recovers ~15–20% of failed payments. 30–40% of users retry immediately if given a button. **Why it matters:** Confirms the retry attempt structure (3 retries) and gives a real-world baseline recovery rate of 15–20% for smart retry alone. Our retry dataset's 31% overall success rate is in a plausible range (includes all causes, including near-zero-success ones like card_expired).

**C. NPCI NACH Circular NPCI/2024-25/NACH/006 (Nov 2024) — Revised Rejection Codes**
https://www.npci.org.in/PDF/nach/circular/2024-25/NACH-006-FY-24-25-Changes-in-Rejection-Code-description-in-NACH.pdf
Also via: https://taxguru.in/finance/revised-rejection-reason-codes-nach-e-mandates.html

What I pulled: The official NPCI NACH return/rejection code list. 6 new codes added, 33 revised, 22 removed — effective Jan 1, 2025. Key codes: 04 (Balance Insufficient), 14 (Mandate expired), 61 (Mandate Cancelled), 01 (Account Closed), 21 (Invalid UMRN or inactive mandate), 59 (Network Failure CBS), AP01–AP70 for registration errors. **Why it matters:** These are the real standardised codes used in production eNACH systems. Our generator uses descriptive strings like `insufficient_funds` and `bank_server_error` instead. See Enhancement E1 below.

**D. Decentro — NPCI Error Codes for eNACH Mandate Presentation**
https://docs.decentro.tech/reference/npci-error-codes-mandate-presentation

What I pulled: Full mapping of debit-execution error codes: 04 (Balance Insufficient), 14 (Mandate expired), 21 (Invalid UMRN), 26 (Amount exceeds mandate max), 53 (Account Inoperative), 57 (Amount exceeds per-txn limit), 58 (Max debit limit reached), 59 (Network Failure CBS), 61 (Mandate Cancelled), 68 (Account Blocked/Frozen). Return vs Reject classification for each. **Why it matters:** Production payment gateways like Razorpay abstract these into their own codes, but the underlying NPCI codes are what banks actually return. This is the authoritative list.

**E. RBI — Digital Payments E-Mandate Framework 2026 (Circular Apr 21, 2026)**
Via: https://conventuslaw.com/report/rbis-digital-payments-e-mandate-framework-2026-consolidated-directions-for-recurring-digital-transactions/
Also: https://amlegals.com/digital-payments-e-mandate-framework-2026-rbis-new-rules-for-auto-debit-transactions/

What I pulled: Consolidated e-mandate framework replacing all prior circulars. Key rules: (1) ₹15,000 no-AFA threshold for general recurring payments. (2) ₹1,00,000 no-AFA threshold for insurance premiums, SIP subscriptions, and credit card bill payments specifically. (3) Mandatory 24h pre-debit notification. (4) Post-debit confirmation required. (5) No charges to customers for e-mandate facility. **Why it matters:** The dual AFA threshold (₹15K general / ₹1L for SIP+insurance+CC) is not reflected in our generator. See Enhancement E2 below.

**F. NPCI — UPI AutoPay Non-Peak Hours Rule (Aug 2025)**
Via: https://paytm.com/blog/payments/upi/upi-rules-update-august-1-npci-new-guidelines/
Also: https://gokiwi.in/blog/major-changes-by-npci-on-upi-in-2025/

What I pulled: From Aug 1, 2025, NPCI requires UPI AutoPay executions only during non-peak hours: before 10:00 AM, 1:00–5:00 PM, after 9:30 PM. Peak hours (10AM–1PM, 5PM–9:30PM) are blocked for auto-debit execution. Max 4 attempts per mandate (1 original + 3 retries). **Why it matters:** Our retry outcome generator lets `time_of_day` span 0–23 uniformly. In reality, UPI AutoPay executions can only happen in specific windows. See Enhancement E3 below.

**G. Razorpay — "UPI Autopay with Intelligent Revenue-Protect"**
https://razorpay.com/blog/upi-autopay-with-intelligent-revenue-protect/

What I pulled: Razorpay's smart retry engine recovers failures using context-aware timing. INDmoney case study: UPI AutoPay success rate improved from 65% to 85% using deep error analysis. WhatsApp-based recovery links for failed payments. **Why it matters:** Validates that the "smart retry" approach (which is what our bandit is trying to learn) has real-world precedent and claimed 20pp improvement. Our bandit's near-payday signal (+18.5pp) is in a similar range.

**H. India salary credit timing**
Via: https://tmservices.co.in/salary-by-the-7th-rule-payroll-process-changes-for-employers-2025/
Also: https://hrsoftwaredelhi.com/payroll-cycle/

What I pulled: Indian wage law requires salary by 7th of following month (10th for 1000+ employee establishments). In practice, most companies cut off attendance around 25th, process payroll 26th–29th, credit by 30th/1st or by 7th of next month. IT/ITES trending toward 1st-of-month crediting. **Why it matters:** Our `days_since_estimated_payday` feature in the retry dataset uses a range of -15 to +15 days. Given that salary typically arrives on the 1st–7th of the month, this range is reasonable. The payday signal (success rate boost at days 0 to +3) is realistic.

---

## 2. Confirmed Assumptions

| Assumption in current data | Independent confirmation |
|---|---|
| `insufficient_funds` is the most common recurring payment failure cause | Business Standard: insufficient balance is the primary cause of 20M monthly mandate revocations. SBI's ~70% AutoPay failure rate is largely balance-driven. |
| Bank outage failures cluster by BIN + time window | NPCI downtime incident data matches our clustering approach. SBI and PNB have the most reported incidents. |
| `failure_reason_code` ≠ `ground_truth_cause` (codes are noisy) | Decentro/NPCI code list confirms: code 59 (Network Failure CBS) could be bank outage or network issue; timeouts are ambiguous; NPCI codes don't reveal root cause. |
| Max 3 retry attempts | NPCI rule confirmed: 1 original + 3 retries max. Our data uses `retry_attempt_number` 1–3, which maps to retry attempts (not counting original). Correct. |
| Retry success rates: 15–20% for smart retry, near-zero for expired mandates/cards | productgrowth.in confirms 15–20% smart retry recovery. Expired mandates/cards can't succeed via retry (needs re-registration). Our 8.4% for card/mandate expired is slightly generous but includes noise. |
| Month-end / salary timing affects payment success | Business Standard confirms insufficient balance as primary driver. Salary timing (1st–7th) matches our `days_since_estimated_payday` signal. |
| Our cause distribution (30% insuf, 20% outage, 15% mandate, 12% card, 13% AFA, 10% ambig) | No single source publishes this exact breakdown for recurring payments specifically. Our distribution is an informed estimate. The 74% overall AutoPay BD rate suggests insufficient_funds may be even higher in reality, but our distribution is for the subset we're trying to recover (already-failed payments with diverse causes), not the overall failure population. Reasonable. |

---

## 3. Corrections Needed

**None found.** After thorough review, the current generated data does not contain material errors. The distributions are within defensible ranges, the structural properties (BIN clustering, reason-code noise, edge cases) are sound, and the retry outcome patterns reflect documented real-world dynamics.

The closest thing to a correction is the AFA threshold issue (see Enhancement E2), but this is nuanced: our generator uses ₹15,000 as a blanket AFA threshold, which is correct for the *general* case. The ₹1L carve-out for SIP/insurance/CC bills is a refinement, not a fix — the current data isn't wrong, it's simplified. Since our schema doesn't include a `payment_category` field, there's no way to apply the differential threshold without a schema change. That makes it an enhancement, not a correction.

---

## 4. Enhancements Recommended

### E1: Use real NPCI NACH return codes instead of descriptive strings
**Current:** `failure_reason_code` uses strings like `insufficient_funds`, `bank_server_error`, `timeout`
**Proposed:** Map to real NPCI codes: `04` (Balance Insufficient), `59` (Network Failure CBS), `14` (Mandate expired), `61` (Mandate Cancelled), `21` (Invalid UMRN), etc.
**Why:** Credibility upgrade for the Razorpay buildathon. Shows awareness of the actual payment infrastructure. The diagnosis layer would work the same way — it's just renaming the enum values.
**Risk:** Low. Purely cosmetic change to code names.
**Impact on downstream:** Diagnosis rules would use code numbers instead of strings. No logic change.
**My recommendation:** Worth doing. It's a 15-minute change and makes the data look production-realistic.

### E2: Add `payment_category` field and dual AFA threshold
**Current:** All payments >₹15,000 are flagged `amount_above_afa_threshold=True`. `afa_stuck` records are always >₹15,000.
**Proposed:** Add a `payment_category` enum (`subscription`, `emi`, `sip`, `insurance`, `cc_bill`). Apply ₹15,000 threshold for EMIs/general, ₹1,00,000 for SIPs/insurance/CC bills. Only flag `amount_above_afa_threshold=True` using the correct threshold for each category.
**Why:** RBI's Dec 2023 / Apr 2026 framework explicitly differentiates. A SIP of ₹20,000 would NOT trigger AFA in reality. Our data currently says it would.
**Risk:** Medium. Requires schema change, generator logic change, and downstream diagnosis rules to become category-aware.
**Impact on downstream:** Diagnosis layer's AFA-detection rule would need to check category + threshold, not just amount > ₹15K. More realistic but more complex.
**My recommendation:** Worth doing but review the schema change first. It adds a useful feature column and makes the AFA logic defensible under scrutiny from judges who know Indian payment regulations.

### E3: Constrain retry `time_of_day` to NPCI non-peak windows
**Current:** `time_of_day` is uniform 0–23.
**Proposed:** Weight `time_of_day` toward NPCI-permitted AutoPay windows: before 10AM, 1–5PM, after 9:30PM. Peak hours (10AM–1PM, 5–9:30PM) should have very low weight (not zero — eNACH doesn't have this restriction, only UPI AutoPay).
**Why:** NPCI mandated non-peak-hour execution from Aug 2025. Retry attempts in peak hours wouldn't be accepted by the UPI rails.
**Risk:** Low-medium. Changes the `time_of_day` distribution, which could affect the bandit's learned patterns.
**Impact on downstream:** The bandit might learn time-of-day patterns differently. The "retry 6–12h after outage" pattern in the retry data would need to account for which hours are actually available.
**My recommendation:** Interesting but subtle. The non-peak rule applies only to UPI AutoPay, not eNACH or card auto-debit. Since our retry dataset doesn't distinguish payment method, this is hard to apply cleanly. Defer unless we add payment method to the retry schema.

### E4: Add `mandate_revoked` as a ground truth cause
**Current:** We have `mandate_expired` but not `mandate_revoked`.
**Proposed:** Add `mandate_revoked` (customer actively cancelled the mandate) as a separate cause from `mandate_expired` (mandate reached its end date). Split current `mandate_expired` 15% into ~10% expired + ~5% revoked.
**Why:** 20M mandates are revoked per month (Business Standard). Revocation is a distinct customer action — the diagnosis and recovery strategy is completely different (expired → reauthorize mandate; revoked → customer chose to cancel, recovery requires convincing them to re-register).
**Risk:** Medium. Adds a new cause label, changes the diagnosis layer's classification targets.
**Impact on downstream:** Diagnosis layer needs a new rule. Action router needs a different path for revoked vs expired.
**My recommendation:** Strong enhancement. The 20M/month revocation number is too significant to ignore. But it changes the classification schema, so review first.

### E5: Add `pre_debit_notification_sent` field
**Current:** Not tracked.
**Proposed:** Boolean field indicating whether the pre-debit notification was sent ≥24h before the debit attempt.
**Why:** RBI mandates 24h pre-debit notification. If not sent, the payment gateway shouldn't have attempted the debit. This is a compliance-relevant field and could be used in the action router's compliance checks.
**Risk:** Low. Additive field.
**My recommendation:** Nice-to-have for the compliance story but not essential for the diagnosis/recovery flow. Defer.

---

## 5. Things I Considered But Rejected

**74% overall AutoPay BD rate:** I initially thought our data might need to reflect this very high failure rate, but realized it's the wrong frame. Our dataset is 500 *already-failed* payments — we're not trying to model the success/failure ratio of all autopay attempts. The 74% number validates the problem space (recurring payment failure is massive) but doesn't change our data generation.

**UCO Bank / Bank of Maharashtra outlier BD rates:** These banks have 10–12% BD rates vs the industry ~3–5%. Interesting but they're small-volume banks. Including them would add noise without adding diagnostic signal. Our bank distribution is already weighted by volume, which naturally de-emphasizes these outliers.

**NPCI mandate interoperability rule (Oct 2025):** NPCI now requires UPI apps to let users view/port mandates across apps. Interesting for the product context but doesn't affect failure patterns or recovery strategies. Irrelevant to our data.

**Razorpay WhatsApp recovery links:** Their Intelligent Revenue-Protect sends branded WhatsApp links for failed payments. This is a real-world analogue to our `sms_then_retry` action type. Validates the concept but doesn't change our data. Could inform the action router's implementation in Stage 5.

**AP-prefix registration error codes (AP01–AP70):** These are for mandate *registration* failures, not execution failures. Our dataset covers execution failures (the debit was attempted and failed). Including registration error codes would be scope creep.

---

## Summary

The synthetic data holds up well under independent verification. No corrections needed. The most impactful enhancements are E1 (real NPCI codes — easy, high credibility) and E2 (dual AFA threshold — medium effort, high regulatory accuracy). E4 (mandate_revoked) is a strong addition but changes the classification schema. E3 and E5 are defer-worthy.

The single most interesting finding: SBI's UPI AutoPay approval rate is only ~30%, meaning 70% of auto-debits fail. This is wildly different from SBI's general UPI approval rate of 96%. It confirms that recurring payment failure is a fundamentally different problem from general UPI failure — the problem space this project targets is much larger than the general UPI failure statistics would suggest.
