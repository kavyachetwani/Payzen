"""Generate 500 synthetic failed recurring payment records.

Distributions calibrated against NPCI, Growww Tech, and Razorpay published data.
See /data/README.md and /references/sources.md for full citation trail.
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
NUM_RECORDS = 500
ANCHOR = datetime(2026, 1, 1)
WINDOW_DAYS = 30
OUTPUT_PATH = Path(__file__).parent / "failed_payments.json"

# ── Bank config: name → (weight, [BIN prefixes]) ──────────────────────────
BANKS = {
    "SBI":            (0.25, ["501126", "501127", "601126"]),
    "HDFC":           (0.15, ["411111", "411112", "436541"]),
    "Bank of Baroda": (0.10, ["420812", "420813"]),
    "ICICI":          (0.08, ["411144", "411145"]),
    "Axis":           (0.07, ["418210", "418211"]),
    "PNB":            (0.06, ["508159", "508160"]),
    "Union Bank":     (0.05, ["519915", "519916"]),
    "Kotak":          (0.05, ["431288", "431289"]),
    "Bank of India":  (0.04, ["508998", "508999"]),
    "Canara":         (0.05, ["508505", "508506"]),
    "IDBI":           (0.04, ["500870", "500871"]),
    "IndusInd":       (0.03, ["402360", "402361"]),
    "Yes Bank":       (0.03, ["457392", "457393"]),
}

CAUSE_DISTRIBUTION = {
    "insufficient_funds": 0.30,
    "bank_outage":        0.20,
    "mandate_expired":    0.15,
    "card_expired":       0.12,
    "afa_stuck":          0.13,
    "ambiguous":          0.10,
}

REASON_CODE_MAP = {
    "insufficient_funds": ["insufficient_funds"],
    "bank_outage":        ["bank_server_error", "timeout", "unknown"],
    "mandate_expired":    ["mandate_expired"],
    "card_expired":       ["card_expired"],
    "afa_stuck":          ["afa_pending", "timeout", "unknown"],
    "ambiguous":          ["insufficient_funds", "bank_server_error", "timeout",
                           "afa_pending", "mandate_expired", "unknown"],
}

PAYMENT_METHODS = ["upi_autopay", "enach", "card_auto_debit"]
PAYMENT_METHOD_WEIGHTS = [0.45, 0.35, 0.20]

# Outage-prone banks (by real downtime incidents)
OUTAGE_BANKS = ["SBI", "PNB", "Bank of Baroda", "Bank of India", "Union Bank", "ICICI"]
OUTAGE_BANK_WEIGHTS = [0.30, 0.25, 0.20, 0.10, 0.08, 0.07]

# Amount ranges by payment type
AMOUNT_RANGES = {
    "subscription": (99, 999),
    "emi":          (2000, 50000),
    "sip":          (500, 25000),
}
AMOUNT_TYPE_WEIGHTS = [0.35, 0.40, 0.25]


def pick_bank(rng: random.Random) -> tuple[str, str]:
    names = list(BANKS.keys())
    weights = [BANKS[n][0] for n in names]
    bank = rng.choices(names, weights=weights, k=1)[0]
    bin_prefix = rng.choice(BANKS[bank][1])
    return bank, bin_prefix


def pick_amount(rng: random.Random, cause: str) -> float:
    if cause == "afa_stuck":
        return round(rng.uniform(15001, 50000), 2)
    amt_type = rng.choices(["subscription", "emi", "sip"], weights=AMOUNT_TYPE_WEIGHTS, k=1)[0]
    lo, hi = AMOUNT_RANGES[amt_type]
    return round(rng.uniform(lo, hi), 2)


def pick_timestamp_for_cause(rng: random.Random, cause: str) -> datetime:
    if cause == "insufficient_funds":
        day = rng.choices(
            range(1, 31),
            weights=[1]*26 + [3, 4, 5, 5],  # heavier at month-end
            k=1,
        )[0]
    elif cause == "bank_outage":
        day = rng.randint(1, 30)
    else:
        day = rng.randint(1, 30)

    hour = rng.choices(
        range(24),
        weights=[1]*10 + [1]*12 + [3, 3],  # slightly heavier 10PM-midnight
        k=1,
    )[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return ANCHOR + timedelta(days=day - 1, hours=hour, minutes=minute, seconds=second)


def generate_outage_incidents(rng: random.Random) -> list[dict]:
    """Generate 7 bank-outage incidents, each producing 10-18 clustered failures."""
    records = []
    # Fixed assignment matching real downtime data: SBI most incidents, PNB second, BoB third
    banks_for_incidents = ["SBI", "SBI", "PNB", "PNB", "Bank of Baroda", "Bank of India", "ICICI"]
    rng.shuffle(banks_for_incidents)

    for incident_idx, bank in enumerate(banks_for_incidents):
        cluster_size = rng.randint(12, 18)
        incident_day = rng.randint(1, 28)
        incident_hour = rng.randint(0, 22)
        incident_start = ANCHOR + timedelta(days=incident_day - 1, hours=incident_hour)

        for _ in range(cluster_size):
            offset_minutes = rng.randint(0, 120)
            ts = incident_start + timedelta(minutes=offset_minutes)
            bin_prefix = rng.choice(BANKS[bank][1])
            reason = rng.choice(["bank_server_error", "timeout", "unknown"])
            amt_type = rng.choices(["subscription", "emi", "sip"], weights=AMOUNT_TYPE_WEIGHTS, k=1)[0]
            lo, hi = AMOUNT_RANGES[amt_type]
            amount = round(rng.uniform(lo, hi), 2)

            records.append({
                "bank_name": bank,
                "bin": bin_prefix,
                "failure_timestamp": ts.isoformat(),
                "failure_reason_code": reason,
                "amount": amount,
                "amount_above_afa_threshold": amount > 15000,
                "ground_truth_cause": "bank_outage",
                "payment_method": rng.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS, k=1)[0],
                "_outage_incident": incident_idx,
            })
    return records


def generate_edge_cases(rng: random.Random, next_id: int) -> list[dict]:
    """Generate 20+ deliberate edge cases as specified in README."""
    cases = []
    base_record = lambda: {
        "customer_prior_success_count": 0,
        "customer_prior_failure_count": 0,
    }

    # 1-2: Missing BIN
    for _ in range(2):
        ts = pick_timestamp_for_cause(rng, "ambiguous")
        cases.append({
            "bank_name": "SBI",
            "bin": "",
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "unknown",
            "amount": round(rng.uniform(500, 5000), 2),
            "amount_above_afa_threshold": False,
            "ground_truth_cause": "ambiguous",
            "payment_method": "upi_autopay",
            "customer_prior_success_count": rng.randint(0, 3),
            "customer_prior_failure_count": rng.randint(0, 2),
            "_edge_case": "missing_bin",
        })

    # 3: Malformed BIN
    ts = pick_timestamp_for_cause(rng, "ambiguous")
    cases.append({
        "bank_name": "HDFC",
        "bin": "41X",
        "failure_timestamp": ts.isoformat(),
        "failure_reason_code": "bank_server_error",
        "amount": 1200.00,
        "amount_above_afa_threshold": False,
        "ground_truth_cause": "ambiguous",
        "payment_method": "enach",
        "customer_prior_success_count": 5,
        "customer_prior_failure_count": 1,
        "_edge_case": "malformed_bin",
    })

    # 4-6: Brand new customer (0 prior history)
    for cause in ["insufficient_funds", "bank_outage", "mandate_expired"]:
        ts = pick_timestamp_for_cause(rng, cause)
        bank, bin_p = pick_bank(rng)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": rng.choice(REASON_CODE_MAP[cause]),
            "amount": pick_amount(rng, cause),
            "amount_above_afa_threshold": False,
            "ground_truth_cause": cause,
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": 0,
            "customer_prior_failure_count": 0,
            "_edge_case": "zero_history",
        })

    # 7-9: Mandate expiry only 1 day before failure
    for _ in range(3):
        ts = pick_timestamp_for_cause(rng, "mandate_expired")
        bank, bin_p = pick_bank(rng)
        expiry = (datetime.fromisoformat(ts.isoformat()) - timedelta(days=1)).strftime("%Y-%m-%d")
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "mandate_expired",
            "amount": pick_amount(rng, "mandate_expired"),
            "amount_above_afa_threshold": False,
            "ground_truth_cause": "mandate_expired",
            "payment_method": rng.choice(["upi_autopay", "enach"]),
            "customer_prior_success_count": rng.randint(3, 20),
            "customer_prior_failure_count": rng.randint(0, 2),
            "mandate_expiry_date": expiry,
            "_edge_case": "mandate_expiry_1day",
        })

    # 10-12: Looks like bank_outage by BIN clustering but is actually insufficient_funds
    # (place these in an outage window timestamp for SBI)
    outage_window_start = ANCHOR + timedelta(days=5, hours=14)
    for i in range(3):
        ts = outage_window_start + timedelta(minutes=rng.randint(0, 90))
        cases.append({
            "bank_name": "SBI",
            "bin": rng.choice(BANKS["SBI"][1]),
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "bank_server_error",
            "amount": round(rng.uniform(2000, 10000), 2),
            "amount_above_afa_threshold": False,
            "ground_truth_cause": "insufficient_funds",
            "payment_method": "upi_autopay",
            "customer_prior_success_count": rng.randint(0, 5),
            "customer_prior_failure_count": rng.randint(2, 6),
            "_edge_case": "false_positive_outage",
        })

    # 13-14: Duplicate customer with different causes
    cust_id = f"CUST_{next_id + 900:05d}"
    for cause in ["insufficient_funds", "mandate_expired"]:
        ts = pick_timestamp_for_cause(rng, cause)
        bank, bin_p = pick_bank(rng)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": rng.choice(REASON_CODE_MAP[cause]),
            "amount": pick_amount(rng, cause),
            "amount_above_afa_threshold": False,
            "ground_truth_cause": cause,
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": 12,
            "customer_prior_failure_count": 3,
            "_edge_case": "duplicate_customer",
            "_forced_customer_id": cust_id,
        })

    # 15-16: Amount exactly at ₹15,000 AFA threshold
    for _ in range(2):
        ts = pick_timestamp_for_cause(rng, "afa_stuck")
        bank, bin_p = pick_bank(rng)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": rng.choice(["afa_pending", "timeout"]),
            "amount": 15000.00,
            "amount_above_afa_threshold": False,  # exactly at, not above
            "ground_truth_cause": "afa_stuck",
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": rng.randint(1, 10),
            "customer_prior_failure_count": rng.randint(0, 3),
            "_edge_case": "exact_afa_threshold",
        })

    # 17-19: bank_server_error reason code but ground truth is bank_outage
    # (already handled in outage gen, but add explicit standalone ones)
    for _ in range(3):
        ts = pick_timestamp_for_cause(rng, "bank_outage")
        bank, bin_p = pick_bank(rng)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "bank_server_error",
            "amount": pick_amount(rng, "bank_outage"),
            "amount_above_afa_threshold": False,
            "ground_truth_cause": "bank_outage",
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": rng.randint(0, 15),
            "customer_prior_failure_count": rng.randint(0, 4),
            "_edge_case": "reason_cause_mismatch",
        })

    # 20-22: timeout reason code on afa_stuck case
    for _ in range(3):
        ts = pick_timestamp_for_cause(rng, "afa_stuck")
        bank, bin_p = pick_bank(rng)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "timeout",
            "amount": round(rng.uniform(15001, 40000), 2),
            "amount_above_afa_threshold": True,
            "ground_truth_cause": "afa_stuck",
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": rng.randint(1, 8),
            "customer_prior_failure_count": rng.randint(0, 2),
            "_edge_case": "timeout_is_afa",
        })

    return cases


def generate():
    rng = random.Random(SEED)

    # Step 1: Generate outage cluster records
    outage_records = generate_outage_incidents(rng)
    num_outage = len(outage_records)

    # Step 2: Generate edge cases
    edge_cases = generate_edge_cases(rng, NUM_RECORDS)
    num_edge = len(edge_cases)

    # Step 3: Count how many of each cause we already have from outage + edge
    cause_counts = {}
    for r in outage_records + edge_cases:
        c = r["ground_truth_cause"]
        cause_counts[c] = cause_counts.get(c, 0) + 1

    # Step 4: Fill remaining records to reach targets
    remaining = NUM_RECORDS - num_outage - num_edge
    fill_records = []

    targets = {cause: max(0, int(NUM_RECORDS * pct) - cause_counts.get(cause, 0))
               for cause, pct in CAUSE_DISTRIBUTION.items()}
    # Adjust to fill exactly 'remaining'
    total_target = sum(targets.values())
    if total_target < remaining:
        targets["insufficient_funds"] += remaining - total_target
    elif total_target > remaining:
        excess = total_target - remaining
        for cause in ["ambiguous", "insufficient_funds", "mandate_expired"]:
            reduce = min(excess, targets[cause])
            targets[cause] -= reduce
            excess -= reduce
            if excess <= 0:
                break

    for cause, count in targets.items():
        for _ in range(count):
            bank, bin_p = pick_bank(rng)
            ts = pick_timestamp_for_cause(rng, cause)
            amount = pick_amount(rng, cause)

            if cause == "card_expired":
                method = "card_auto_debit"
            else:
                method = rng.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS, k=1)[0]

            reason = rng.choice(REASON_CODE_MAP[cause])

            rec = {
                "bank_name": bank,
                "bin": bin_p,
                "failure_timestamp": ts.isoformat(),
                "failure_reason_code": reason,
                "amount": amount,
                "amount_above_afa_threshold": amount > 15000,
                "ground_truth_cause": cause,
                "payment_method": method,
                "customer_prior_success_count": rng.randint(0, 30),
                "customer_prior_failure_count": rng.randint(0, 8),
            }
            fill_records.append(rec)

    all_records = outage_records + edge_cases + fill_records

    # Step 5: Assign IDs, customer_ids, mandate_ids, and fill missing fields
    rng.shuffle(all_records)  # mix everything together
    customer_pool = [f"CUST_{i:05d}" for i in range(1, 350)]
    mandate_pool = [f"MND_{i:05d}" for i in range(1, 300)]

    for i, rec in enumerate(all_records):
        rec["payment_id"] = f"PAY_{i + 1:05d}"

        if "_forced_customer_id" in rec:
            rec["customer_id"] = rec.pop("_forced_customer_id")
        else:
            rec["customer_id"] = rng.choice(customer_pool)

        rec["mandate_id"] = rng.choice(mandate_pool)

        if "mandate_expiry_date" not in rec:
            ts = datetime.fromisoformat(rec["failure_timestamp"])
            if rec["ground_truth_cause"] == "mandate_expired":
                days_before = rng.randint(1, 60)
                rec["mandate_expiry_date"] = (ts - timedelta(days=days_before)).strftime("%Y-%m-%d")
            else:
                days_after = rng.randint(30, 365)
                rec["mandate_expiry_date"] = (ts + timedelta(days=days_after)).strftime("%Y-%m-%d")

        if "customer_prior_success_count" not in rec:
            rec["customer_prior_success_count"] = rng.randint(0, 20)
        if "customer_prior_failure_count" not in rec:
            rec["customer_prior_failure_count"] = rng.randint(0, 5)

        # Clean internal markers
        rec.pop("_outage_incident", None)
        rec.pop("_edge_case", None)

    # Reorder fields for readability
    field_order = [
        "payment_id", "customer_id", "mandate_id", "amount", "payment_method",
        "bank_name", "bin", "failure_timestamp", "failure_reason_code",
        "customer_prior_success_count", "customer_prior_failure_count",
        "mandate_expiry_date", "amount_above_afa_threshold", "ground_truth_cause",
    ]
    ordered = [{k: rec[k] for k in field_order if k in rec} for rec in all_records]

    OUTPUT_PATH.write_text(json.dumps(ordered, indent=2, default=str))

    # Print summary
    print(f"Generated {len(ordered)} records → {OUTPUT_PATH}")
    print()
    _print_summary(ordered)
    return ordered


def _print_summary(records):
    from collections import Counter

    causes = Counter(r["ground_truth_cause"] for r in records)
    banks = Counter(r["bank_name"] for r in records)
    methods = Counter(r["payment_method"] for r in records)
    reasons = Counter(r["failure_reason_code"] for r in records)

    print("── Cause Distribution ──")
    for cause in sorted(causes, key=causes.get, reverse=True):
        pct = causes[cause] / len(records) * 100
        print(f"  {cause:25s} {causes[cause]:4d}  ({pct:5.1f}%)")

    print("\n── Bank Distribution ──")
    for bank in sorted(banks, key=banks.get, reverse=True):
        pct = banks[bank] / len(records) * 100
        print(f"  {bank:25s} {banks[bank]:4d}  ({pct:5.1f}%)")

    print("\n── Payment Method Distribution ──")
    for m in sorted(methods, key=methods.get, reverse=True):
        pct = methods[m] / len(records) * 100
        print(f"  {m:25s} {methods[m]:4d}  ({pct:5.1f}%)")

    print("\n── Failure Reason Code Distribution ──")
    for r in sorted(reasons, key=reasons.get, reverse=True):
        pct = reasons[r] / len(records) * 100
        print(f"  {r:25s} {reasons[r]:4d}  ({pct:5.1f}%)")

    # Outage cluster verification
    print("\n── Bank Outage Cluster Verification ──")
    outage_recs = [r for r in records if r["ground_truth_cause"] == "bank_outage"]
    from itertools import groupby
    outage_recs_sorted = sorted(outage_recs, key=lambda r: (r["bank_name"], r["bin"], r["failure_timestamp"]))
    by_bank = {}
    for r in outage_recs_sorted:
        by_bank.setdefault(r["bank_name"], []).append(r)
    for bank, recs in sorted(by_bank.items(), key=lambda x: -len(x[1])):
        print(f"  {bank}: {len(recs)} outage records")
        timestamps = sorted(datetime.fromisoformat(r["failure_timestamp"]) for r in recs)
        if len(timestamps) >= 2:
            span = timestamps[-1] - timestamps[0]
            print(f"    Time span: {span}")
            bins_used = set(r["bin"] for r in recs)
            print(f"    BINs: {', '.join(sorted(bins_used))}")

    # Edge case count
    edge_indicators = sum(1 for r in records if (
        r["bin"] in ("", "41X") or
        r["customer_prior_success_count"] == 0 and r["customer_prior_failure_count"] == 0 or
        r["amount"] == 15000.00
    ))
    print(f"\n  Edge-case-like records (approx): {edge_indicators}")


if __name__ == "__main__":
    generate()
