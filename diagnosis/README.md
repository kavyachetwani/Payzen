# Diagnosis Engine

SQL-based root-cause diagnosis for failed recurring payments. Zero LLM — pure rule matching over a normalized SQLite schema.

## Architecture

- **db.py** — Normalized schema: `banks`, `customers`, `mandates`, `payments`, `ground_truth`. The diagnosis layer NEVER queries `ground_truth`; it exists only for evaluation.
- **rules.py** — 7 priority-ordered rules (first match wins). Configurable BIN-clustering parameters.
- **tune.py** — Grid search over 48 parameter combinations on the train split only.
- **diagnose_batch.py** — Runs diagnosis on all 500 records with the tuned config.
- **evaluate.py** — Evaluates on held-out test split (100 records). Prints 6 sections.

## Rules (priority order)

| # | Rule | Signal | Confidence |
|---|------|--------|------------|
| 1 | mandate_expired | code='14' + expiry < timestamp | 0.95 |
| 2 | mandate_revoked | code='61' | 0.90 |
| 3 | card_expired | code='card_expired' + card_auto_debit | 0.90 |
| 4 | bank_outage | BIN-prefix cluster in time window | 0.70–0.90 |
| 5 | afa_stuck | afa_pending/timeout/unknown + above AFA threshold | 0.60–0.80 |
| 6 | insufficient_funds | code='04' (0.85) or failure>success history (0.55) | 0.55–0.85 |
| 7 | ambiguous | fallback | 0.30 |

## Tuning Results

Grid: 3 prefix lengths x 4 time windows x 4 count thresholds = 48 configs.

**Best config**: `bin_prefix_length=4, cluster_time_window_hours=2.0, cluster_count_threshold=3`
**Train accuracy**: 95.0% (380/400). Four configs tied at 95.0%; this one was selected first.

## Test-Set Evaluation

**Overall accuracy: 95/100 = 95.0%**

| Cause | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| insufficient_funds | 96.6% | 93.3% | 94.9% | 30 |
| bank_outage | 95.0% | 95.0% | 95.0% | 20 |
| mandate_expired | 100.0% | 100.0% | 100.0% | 10 |
| mandate_revoked | 100.0% | 100.0% | 100.0% | 5 |
| card_expired | 100.0% | 100.0% | 100.0% | 12 |
| afa_stuck | 100.0% | 92.3% | 96.0% | 13 |
| ambiguous | 75.0% | 90.0% | 81.8% | 10 |

### Confidence Calibration

| Bucket | Count | Correct | Actual% |
|--------|-------|---------|---------|
| 0.3-0.4 | 12 | 9 | 75.0% |
| 0.6-0.7 | 11 | 11 | 100.0% |
| 0.7-0.8 | 1 | 0 | 0.0% |
| 0.8-0.9 | 31 | 30 | 96.8% |
| 0.9-1.0 | 45 | 45 | 100.0% |

High-confidence predictions (>=0.8) are 98.7% correct (75/76). Low-confidence (0.3) bucket is 75% — slightly overconfident but acceptable for a fallback tier.

### 5 Misclassifications

1. **PAY_00177**: true=ambiguous, pred=insufficient_funds — ambiguous by design, any guess is valid
2. **PAY_00016**: true=insufficient_funds, pred=bank_outage — SBI BIN fell in outage window (false positive)
3. **PAY_00117**: true=afa_stuck, pred=ambiguous — exact AFA threshold edge case, below-threshold flag
4. **PAY_00418**: true=insufficient_funds, pred=ambiguous — reason code '59', no cluster match
5. **PAY_00139**: true=bank_outage, pred=ambiguous — BIN cluster count below threshold

## Known Weaknesses

1. **False-positive outage detection**: A legitimate insufficient_funds payment from SBI during an outage window gets swept into the bank_outage cluster.
2. **AFA threshold boundary**: The exact-threshold edge case (Rs 15,000) has `amount_above_afa_threshold=False`, so Rule 5 misses it. This is a data-generation artifact (strictly above vs >=).
3. **Ambiguous precision**: 75% precision — 1 record that's truly insufficient_funds gets predicted as ambiguous because reason code '59' doesn't match any specific rule.
4. **No temporal learning**: Rules are static; the engine doesn't learn from retry outcomes. By design — the decision layer (Stage 4+) handles adaptation.

## Known Limitations & Production Improvements

The current BIN-cluster threshold is an absolute count (>=3), calibrated for this dataset's scale (~17 failures/day). In production, this should be replaced with a relative threshold (e.g., 3x the historical average failure rate for that BIN prefix in the same time window) so it scales automatically with merchant transaction volume. A small merchant processing 100 payments/day would correctly flag 3 co-failures as unusual, while a large merchant processing 50,000/day would need a proportionally higher threshold to avoid false positives from normal background decline rates.
