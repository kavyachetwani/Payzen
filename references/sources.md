# Research & References

Sources used to calibrate the synthetic data, validate assumptions, and ground the architecture decisions in this project. These are hand-picked — not a dump of everything I Googled, but the specific sources that actually shaped parameters in the codebase.

---

## Primary sources (directly informed synthetic data distributions)

### NPCI — UPI Ecosystem Statistics
https://www.npci.org.in/statistics/upi-ecosystem-statistics

What I pulled from this: bank-wise UPI transaction volumes, approval rates (BD% = business decline, TD% = technical decline), and the bank downtime incident table. The approval rates by bank directly informed the `bank_name` distribution and the bank-outage clustering patterns in the synthetic dataset — e.g., SBI processes the most volume but has historically reported more downtime incidents than HDFC or Axis.

Key numbers used:
- SBI: 96.11% approved, 3.86% business decline — highest absolute volume of failures because it's also the highest volume bank
- UCO Bank: 88.36% approved, 11.63% BD — outlier, disproportionately high decline rate
- Bank of Maharashtra: 89.56% approved, 10.43% BD — similar outlier pattern
- Technical decline rates across most major banks sit at 0.01–0.17%, confirming NPCI's published ~0.3% aggregate TD figure
- Downtime incidents: SBI had 5 incidents / 5h39m downtime in the reporting period; PNB had 4 incidents / 7h57m — these are the banks most likely to produce the "bank outage cluster" pattern in real data

### VyaparGateway — UPI Payment Failure Rate in India 2026
https://vyapargateway.com/blog/upi-payment-failure-rate-india-2026

What I pulled: the 0.3–0.5% NPCI technical decline figure with the context that at 18,000 crore annual transactions this still means ~54 crore failed transactions/year. Also the peak failure periods (month-end salary/EMI clustering, festival days, 10PM–midnight batch processing window, first business day after holidays) — these directly shaped the `failure_timestamp` clustering logic in the data generator and the `days_since_estimated_payday` feature in the retry-outcome dataset.

Bank-wise availability tiers (also from this source):
- Large private banks (HDFC, ICICI, Axis): >99.9% availability
- SBI: 99.3–99.7%, periodic dips
- Public sector (PNB, BOB, Canara): 99.0–99.5%
- Small finance / co-op banks: most variable, can dip below 99%

### Growww Tech — UPI Fails 10% of the Time
https://growwwtech.com/blog/upi-payments-ecommerce-india

What I pulled: the failure-cause breakdown table — the only source I found that puts approximate percentage shares on failure reasons from a merchant's-eye perspective (not NPCI's infrastructure-only view). Used to calibrate the `ground_truth_cause` distribution:
- Bank server downtime/timeout: 35–40% of failures
- UPI app crash/hang: 15–20%
- Wrong PIN: 10–15%
- Session timeout (customer too slow): 10–15%
- Network connectivity: 10–15%
- Daily limit exceeded: 5–10%

Note: this is a Shopify services company — the article is partly marketing their integration work. But the failure-cause breakdown is consistent with what the NPCI data and Razorpay's blog describe qualitatively, so I used the numbers as calibration anchors, not gospel. Cited with that caveat.

### Razorpay — Online Payment Failure: Reasons & How to Handle Them in 2026
https://razorpay.com/blog/online-payments-failure-reasons/

What I pulled: Razorpay's own taxonomy of failure types (consumer-related, merchant-induced, data transmission glitches, unsuccessful payment attempts). This shaped how the synthetic records assign `failure_reason_code` vs. `ground_truth_cause` — importantly, the reason code the system sees often differs from the actual root cause (e.g., a `bank_server_error` reason code can mask a bank-wide outage, and a `timeout` can be either network or bank-side). The distinction between "what the system reports" and "what actually happened" is a deliberate feature of the synthetic data, not a bug.

Also confirmed: Razorpay's own refund/reconciliation flow involves polling acquiring banks to check if a "failed" payment was actually successful — relevant context for why the diagnosis layer needs to distinguish genuine failures from false-failure reports.

---

## Secondary sources (context and validation, not direct parameter inputs)

### Worldline India — Q3 Quick Peek 2025: India Pays in Seconds
Attached as PDF in this folder: `worldline-q3-2025-india-payments.pdf`

Market context on India's digital payments landscape: UPI hit 59.33 billion transactions in Q3 2025 (+33.5% YoY), P2M growing faster than P2P (37.46B vs 21.65B), average ticket size declining to ₹1,262 (from ₹1,363) as UPI penetrates low-value daily retail. Credit card issuance at 113.39 million, relevant because card-based recurring payments (auto-debit mandates) are one of the three payment methods in the synthetic dataset.

Note: Worldline sold its Indian operations to BillDesk in August 2026, so this is likely one of the last India-specific reports they'll publish under the Worldline brand. Still valid data for the Q3 2025 period it covers.

### RBI — Payment System Indicators
https://www.rbi.org.in/ (navigate to Payment and Settlement Systems → Payment System Indicators)

Used to cross-check NPCI's numbers and confirm eNACH/mandate volume trends. Didn't pull specific parameters from here but used it as a sanity check that the scale assumptions in the synthetic data are in the right ballpark.

---

## Sources added during Stage 2.5 validation (independent research, Aug 2026)

### Business Standard — UPI AutoPay Revocations (Sep 2025)
https://www.business-standard.com/finance/news/upi-autopay-revocations-hit-20-mn-monthly-over-low-customer-balances-125090700500_1.html

What I pulled: 20M UPI AutoPay mandates revoked monthly due to insufficient balance. SBI auto-debit approval rate is only ~30% (vs 96% for general UPI). Business decline across top 50 banks for AutoPay averages ~74%. Mandate registrations hit 50M/month (July 2025), executions at 808M/month. This is the single most important number for framing the problem space — recurring payment failure is fundamentally different from (and much worse than) general UPI failure.

### NPCI — NACH Return/Rejection Codes (Circular NPCI/2024-25/NACH/006, Nov 2024)
https://www.npci.org.in/PDF/nach/circular/2024-25/NACH-006-FY-24-25-Changes-in-Rejection-Code-description-in-NACH.pdf
Also via Decentro API docs: https://docs.decentro.tech/reference/npci-error-codes-mandate-presentation

What I pulled: The authoritative list of NPCI NACH debit-execution return codes. Key codes: 04 (Balance Insufficient), 14 (Mandate expired), 21 (Invalid UMRN/inactive mandate), 59 (Network Failure CBS), 61 (Mandate Cancelled), 68 (Account Blocked/Frozen), 26 (Amount exceeds mandate max), 57/58 (Amount/debit limit exceeded). Not yet used in the generator (we use descriptive strings), but documented in VALIDATION_REPORT.md as Enhancement E1 — switching to real codes is a credibility upgrade.

### RBI — Digital Payments E-Mandate Framework 2026 (Apr 21, 2026)
Via: https://conventuslaw.com/report/rbis-digital-payments-e-mandate-framework-2026-consolidated-directions-for-recurring-digital-transactions/

What I pulled: Consolidated e-mandate directions replacing all prior circulars. Key regulatory facts: (1) ₹15,000 no-AFA threshold for general recurring payments; (2) ₹1,00,000 no-AFA threshold for insurance premiums, mutual fund SIPs, and credit card bill payments; (3) mandatory 24h pre-debit notification; (4) post-debit confirmation required. The dual AFA threshold is documented in VALIDATION_REPORT.md as Enhancement E2 — not yet applied to the generator.

### NPCI — UPI AutoPay Non-Peak Hours Execution Rule (Aug 2025)
Via: https://paytm.com/blog/payments/upi/upi-rules-update-august-1-npci-new-guidelines/

What I pulled: From Aug 1, 2025, NPCI requires UPI AutoPay executions only during non-peak hours: before 10AM, 1–5PM, after 9:30PM. Peak hours (10AM–1PM, 5–9:30PM) are blocked. This applies to UPI AutoPay only (not eNACH or card auto-debit). Documented as Enhancement E3 — not yet applied because the retry dataset doesn't track payment method.

### productgrowth.in — UPI AutoPay Design Guide
https://productgrowth.in/insights/fintech/upi-autopay-guide/

What I pulled: UPI AutoPay failure rate is 8–15% (vs 2–3% for card mandates). Smart retry recovers ~15–20% of failed payments. Retry windows at 24h, 72h, 168h. 30–40% of users retry immediately if given a button. Used to validate our retry outcome dataset's overall success rate (31%) and the retry attempt number distribution.

---

## What I deliberately did NOT include

- The Bloomberg article on India's digital payments vs. cash demand (https://www.bloomberg.com/news/articles/2026-08-18/india-s-digital-payments-boom-fails-to-dent-demand-for-cash) — interesting macro context but doesn't contribute any parameter to the synthetic data or the recovery logic. Including it would be padding.
- Generic "what is UPI" explainer articles — no shortage of these, none added anything the primary sources above didn't already cover better.
- Razorpay's Facebook video content on failed payments — useful for understanding their narrative framing but not citable as data sources.