# Engineering Notes

## Bug #1 — mandate_expiry overwrite in normalized schema (Stage 3)

**Impact:** diagnosis accuracy stuck at 90.8%, ~5 mandate_expired records silently misclassified as ambiguous

**What happened:**

I normalized the payment data into separate tables — payments, customers, banks, mandates. The mandates table was keyed by `mandate_id` with one row per mandate. The loader did:

```python
mandates[mid] = (r["customer_id"], r.get("mandate_expiry_date", ""))
```

Problem: multiple payment records can share a `mandate_id` (same customer, same recurring mandate, different billing cycles). Each record carries its own `mandate_expiry_date` in the source JSON. But `mandates` is a dict, so the last record to load for a given `mandate_id` overwrites the previous one's expiry date.

Concretely: `PAY_00050` has mandate `M_012` with expiry `2025-12-15` (before its failure date, correctly expired). `PAY_00300` also has `M_012` but with expiry `2026-02-01` (still active at its own failure date). After loading, the mandates table stores `2026-02-01` for `M_012`. When the diagnosis engine looks up PAY_00050's mandate, it gets the wrong expiry date, thinks the mandate is still valid, and the `mandate_expired` rule doesn't fire. Record falls through to `ambiguous` at confidence 0.30.

**How I found it:**

Took a while. The rule logic was obviously correct — `reason_code == '14' AND expiry < timestamp`. The source JSON was correct. Ran the rule manually against hardcoded values from the JSON, it returned the right answer. So the logic was fine, the data was fine, but together they produced the wrong result.

Eventually ran a raw SQL query against the loaded DB for one of the failing records and saw the expiry date was wrong in the database. That pointed straight to the loader. Printed the mandates dict mid-load and watched the overwrite happen in real time.

**Fix:**

Added `mandate_expiry_date` as a column on the payments table directly. Each payment record now carries its own expiry date independent of the shared mandate. Changed the diagnosis query from `m.expiry_date` (mandates join) to `p.mandate_expiry_date` (payments table). The mandates table still exists for other potential uses but diagnosis no longer depends on it for expiry dates.

Train accuracy went from 90.8% → 95.0% immediately. All 5 previously misclassified mandate_expired records snapped into place.

**Takeaway:**

Normalizing into a mandates table was the "correct" relational modeling choice but it silently assumed one expiry date per mandate. In reality the same mandate shows up across multiple billing periods with different state. Per-payment denormalization of the expiry field is the right tradeoff here — slightly redundant, but the diagnosis layer doesn't get silently corrupted by load order.
