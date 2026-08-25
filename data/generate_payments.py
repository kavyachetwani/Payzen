"""Generate 500 synthetic failed recurring payment records.

Distributions calibrated against NPCI, Growww Tech, and Razorpay published data.
Reason codes use real NPCI NACH return codes (circular NPCI/2024-25/NACH/006).
AFA thresholds are category-aware per RBI e-mandate framework 2026.
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
    "mandate_expired":    0.10,
    "mandate_revoked":    0.05,
    "card_expired":       0.12,
    "afa_stuck":          0.13,
    "ambiguous":          0.10,
}

# Real NPCI NACH return codes (circular NPCI/2024-25/NACH/006)
# 04 = Balance Insufficient, 59 = Network Failure (CBS), 14 = Mandate expired,
# 61 = Mandate Cancelled, card_expired = card network code (no NACH equivalent),
# afa_pending = UPI-specific (no NACH equivalent), unknown = unmapped
REASON_CODE_MAP = {
    "insufficient_funds": ["04"],
    "bank_outage":        ["59", "timeout", "unknown"],
    "mandate_expired":    ["14"],
    "mandate_revoked":    ["61"],
    "card_expired":       ["card_expired"],
    "afa_stuck":          ["afa_pending", "timeout", "unknown"],
    "ambiguous":          ["04", "59", "timeout", "afa_pending", "14", "unknown"],
}

PAYMENT_METHODS = ["upi_autopay", "enach", "card_auto_debit"]
PAYMENT_METHOD_WEIGHTS = [0.45, 0.35, 0.20]

OUTAGE_BANKS = ["SBI", "PNB", "Bank of Baroda", "Bank of India", "Union Bank", "ICICI"]

# Payment categories and their weights
PAYMENT_CATEGORIES = ["subscription", "emi", "sip", "insurance", "cc_bill"]
CATEGORY_WEIGHTS = [0.30, 0.35, 0.15, 0.10, 0.10]

# Amount ranges by payment category
AMOUNT_RANGES = {
    "subscription": (99, 999),
    "emi":          (2000, 50000),
    "sip":          (500, 25000),
    "insurance":    (1000, 50000),
    "cc_bill":      (500, 80000),
}

# AFA thresholds per RBI e-mandate framework 2026
# ₹15,000 for general (subscription, emi); ₹1,00,000 for sip, insurance, cc_bill
AFA_THRESHOLDS = {
    "subscription": 15000,
    "emi":          15000,
    "sip":          100000,
    "insurance":    100000,
    "cc_bill":      100000,
}


def pick_bank(rng: random.Random) -> tuple[str, str]:
    names = list(BANKS.keys())
    weights = [BANKS[n][0] for n in names]
    bank = rng.choices(names, weights=weights, k=1)[0]
    bin_prefix = rng.choice(BANKS[bank][1])
    return bank, bin_prefix


def pick_category(rng: random.Random, cause: str) -> str:
    if cause == "card_expired":
        return rng.choices(["subscription", "emi", "insurance", "cc_bill"],
                           weights=[0.30, 0.40, 0.15, 0.15], k=1)[0]
    if cause == "afa_stuck":
        return rng.choices(["emi", "sip", "insurance"],
                           weights=[0.60, 0.25, 0.15], k=1)[0]
    return rng.choices(PAYMENT_CATEGORIES, weights=CATEGORY_WEIGHTS, k=1)[0]


def pick_amount(rng: random.Random, cause: str, category: str) -> float:
    if cause == "afa_stuck":
        threshold = AFA_THRESHOLDS[category]
        hi = max(threshold * 3, 150000)
        return round(rng.uniform(threshold + 1, hi), 2)
    lo, hi = AMOUNT_RANGES[category]
    return round(rng.uniform(lo, hi), 2)


def is_above_afa(amount: float, category: str) -> bool:
    return amount > AFA_THRESHOLDS[category]


def pick_notification(rng: random.Random, cause: str) -> bool:
    if cause == "mandate_revoked":
        return rng.random() < 0.60
    return rng.random() < 0.80


def pick_timestamp_for_cause(rng: random.Random, cause: str) -> datetime:
    if cause == "insufficient_funds":
        day = rng.choices(
            range(1, 31),
            weights=[1]*26 + [3, 4, 5, 5],
            k=1,
        )[0]
    else:
        day = rng.randint(1, 30)

    hour = rng.choices(
        range(24),
        weights=[1]*10 + [1]*12 + [3, 3],
        k=1,
    )[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return ANCHOR + timedelta(days=day - 1, hours=hour, minutes=minute, seconds=second)


def generate_outage_incidents(rng: random.Random) -> list[dict]:
    """Generate 7 bank-outage incidents, each producing 12-18 clustered failures."""
    records = []
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
            reason = rng.choice(["59", "timeout", "unknown"])
            category = rng.choices(PAYMENT_CATEGORIES, weights=CATEGORY_WEIGHTS, k=1)[0]
            lo, hi = AMOUNT_RANGES[category]
            amount = round(rng.uniform(lo, hi), 2)

            records.append({
                "bank_name": bank,
                "bin": bin_prefix,
                "failure_timestamp": ts.isoformat(),
                "failure_reason_code": reason,
                "amount": amount,
                "payment_category": category,
                "amount_above_afa_threshold": is_above_afa(amount, category),
                "pre_debit_notification_sent": rng.random() < 0.80,
                "ground_truth_cause": "bank_outage",
                "payment_method": rng.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS, k=1)[0],
                "_outage_incident": incident_idx,
            })
    return records


def generate_edge_cases(rng: random.Random, next_id: int) -> list[dict]:
    """Generate 20+ deliberate edge cases as specified in README."""
    cases = []

    # 1-2: Missing BIN
    for _ in range(2):
        ts = pick_timestamp_for_cause(rng, "ambiguous")
        cases.append({
            "bank_name": "SBI",
            "bin": "",
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "unknown",
            "amount": round(rng.uniform(500, 5000), 2),
            "payment_category": "subscription",
            "amount_above_afa_threshold": False,
            "pre_debit_notification_sent": True,
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
        "failure_reason_code": "59",
        "amount": 1200.00,
        "payment_category": "subscription",
        "amount_above_afa_threshold": False,
        "pre_debit_notification_sent": True,
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
        category = pick_category(rng, cause)
        amount = pick_amount(rng, cause, category)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": rng.choice(REASON_CODE_MAP[cause]),
            "amount": amount,
            "payment_category": category,
            "amount_above_afa_threshold": is_above_afa(amount, category),
            "pre_debit_notification_sent": pick_notification(rng, cause),
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
        category = pick_category(rng, "mandate_expired")
        amount = pick_amount(rng, "mandate_expired", category)
        expiry = (ts - timedelta(days=1)).strftime("%Y-%m-%d")
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "14",
            "amount": amount,
            "payment_category": category,
            "amount_above_afa_threshold": is_above_afa(amount, category),
            "pre_debit_notification_sent": pick_notification(rng, "mandate_expired"),
            "ground_truth_cause": "mandate_expired",
            "payment_method": rng.choice(["upi_autopay", "enach"]),
            "customer_prior_success_count": rng.randint(3, 20),
            "customer_prior_failure_count": rng.randint(0, 2),
            "mandate_expiry_date": expiry,
            "_edge_case": "mandate_expiry_1day",
        })

    # 10-12: Looks like bank_outage by BIN clustering but is actually insufficient_funds
    outage_window_start = ANCHOR + timedelta(days=5, hours=14)
    for i in range(3):
        ts = outage_window_start + timedelta(minutes=rng.randint(0, 90))
        cases.append({
            "bank_name": "SBI",
            "bin": rng.choice(BANKS["SBI"][1]),
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "59",
            "amount": round(rng.uniform(2000, 10000), 2),
            "payment_category": "emi",
            "amount_above_afa_threshold": False,
            "pre_debit_notification_sent": True,
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
        category = pick_category(rng, cause)
        amount = pick_amount(rng, cause, category)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": rng.choice(REASON_CODE_MAP[cause]),
            "amount": amount,
            "payment_category": category,
            "amount_above_afa_threshold": is_above_afa(amount, category),
            "pre_debit_notification_sent": pick_notification(rng, cause),
            "ground_truth_cause": cause,
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": 12,
            "customer_prior_failure_count": 3,
            "_edge_case": "duplicate_customer",
            "_forced_customer_id": cust_id,
        })

    # 15-16: Amount exactly at ₹15,000 AFA threshold (emi category)
    for _ in range(2):
        ts = pick_timestamp_for_cause(rng, "afa_stuck")
        bank, bin_p = pick_bank(rng)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": rng.choice(["afa_pending", "timeout"]),
            "amount": 15000.00,
            "payment_category": "emi",
            "amount_above_afa_threshold": False,
            "pre_debit_notification_sent": pick_notification(rng, "afa_stuck"),
            "ground_truth_cause": "afa_stuck",
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": rng.randint(1, 10),
            "customer_prior_failure_count": rng.randint(0, 3),
            "_edge_case": "exact_afa_threshold",
        })

    # 17-19: Network failure code but ground truth is bank_outage
    for _ in range(3):
        ts = pick_timestamp_for_cause(rng, "bank_outage")
        bank, bin_p = pick_bank(rng)
        category = pick_category(rng, "bank_outage")
        amount = pick_amount(rng, "bank_outage", category)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "59",
            "amount": amount,
            "payment_category": category,
            "amount_above_afa_threshold": is_above_afa(amount, category),
            "pre_debit_notification_sent": pick_notification(rng, "bank_outage"),
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
        category = rng.choice(["emi", "sip"])
        amount = pick_amount(rng, "afa_stuck", category)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "timeout",
            "amount": amount,
            "payment_category": category,
            "amount_above_afa_threshold": True,
            "pre_debit_notification_sent": pick_notification(rng, "afa_stuck"),
            "ground_truth_cause": "afa_stuck",
            "payment_method": rng.choice(PAYMENT_METHODS),
            "customer_prior_success_count": rng.randint(1, 8),
            "customer_prior_failure_count": rng.randint(0, 2),
            "_edge_case": "timeout_is_afa",
        })

    # 23-25: mandate_revoked — customer saw notification and cancelled
    for _ in range(3):
        ts = pick_timestamp_for_cause(rng, "mandate_revoked")
        bank, bin_p = pick_bank(rng)
        category = pick_category(rng, "mandate_revoked")
        amount = pick_amount(rng, "mandate_revoked", category)
        cases.append({
            "bank_name": bank,
            "bin": bin_p,
            "failure_timestamp": ts.isoformat(),
            "failure_reason_code": "61",
            "amount": amount,
            "payment_category": category,
            "amount_above_afa_threshold": is_above_afa(amount, category),
            "pre_debit_notification_sent": True,
            "ground_truth_cause": "mandate_revoked",
            "payment_method": rng.choice(["upi_autopay", "enach"]),
            "customer_prior_success_count": rng.randint(1, 15),
            "customer_prior_failure_count": rng.randint(0, 3),
            "_edge_case": "revoked_after_notification",
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
            category = pick_category(rng, cause)
            amount = pick_amount(rng, cause, category)

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
                "payment_category": category,
                "amount_above_afa_threshold": is_above_afa(amount, category),
                "pre_debit_notification_sent": pick_notification(rng, cause),
                "ground_truth_cause": cause,
                "payment_method": method,
                "customer_prior_success_count": rng.randint(0, 30),
                "customer_prior_failure_count": rng.randint(0, 8),
            }
            fill_records.append(rec)

    all_records = outage_records + edge_cases + fill_records

    # Step 5: Assign IDs, customer_ids, mandate_ids, and fill missing fields
    rng.shuffle(all_records)
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
            elif rec["ground_truth_cause"] == "mandate_revoked":
                days_after = rng.randint(30, 365)
                rec["mandate_expiry_date"] = (ts + timedelta(days=days_after)).strftime("%Y-%m-%d")
            else:
                days_after = rng.randint(30, 365)
                rec["mandate_expiry_date"] = (ts + timedelta(days=days_after)).strftime("%Y-%m-%d")

        if "customer_prior_success_count" not in rec:
            rec["customer_prior_success_count"] = rng.randint(0, 20)
        if "customer_prior_failure_count" not in rec:
            rec["customer_prior_failure_count"] = rng.randint(0, 5)

        rec.pop("_outage_incident", None)
        rec.pop("_edge_case", None)

    field_order = [
        "payment_id", "customer_id", "mandate_id", "amount", "payment_category",
        "payment_method", "bank_name", "bin", "failure_timestamp",
        "failure_reason_code", "customer_prior_success_count",
        "customer_prior_failure_count", "mandate_expiry_date",
        "amount_above_afa_threshold", "pre_debit_notification_sent",
        "ground_truth_cause",
    ]
    ordered = [{k: rec[k] for k in field_order if k in rec} for rec in all_records]

    OUTPUT_PATH.write_text(json.dumps(ordered, indent=2, default=str))

    print(f"Generated {len(ordered)} records → {OUTPUT_PATH}")
    print()
    _print_summary(ordered)
    return ordered


def _print_summary(records):
    from collections import Counter

    n = len(records)
    causes = Counter(r["ground_truth_cause"] for r in records)
    banks = Counter(r["bank_name"] for r in records)
    methods = Counter(r["payment_method"] for r in records)
    reasons = Counter(r["failure_reason_code"] for r in records)
    categories = Counter(r["payment_category"] for r in records)
    notif = Counter(r["pre_debit_notification_sent"] for r in records)

    print("── Cause Distribution ──")
    for cause in sorted(causes, key=causes.get, reverse=True):
        print(f"  {cause:25s} {causes[cause]:4d}  ({causes[cause]/n*100:5.1f}%)")

    print("\n── Bank Distribution ──")
    for bank in sorted(banks, key=banks.get, reverse=True):
        print(f"  {bank:25s} {banks[bank]:4d}  ({banks[bank]/n*100:5.1f}%)")

    print("\n── Payment Method Distribution ──")
    for m in sorted(methods, key=methods.get, reverse=True):
        print(f"  {m:25s} {methods[m]:4d}  ({methods[m]/n*100:5.1f}%)")

    print("\n── Payment Category Distribution ──")
    for c in sorted(categories, key=categories.get, reverse=True):
        print(f"  {c:25s} {categories[c]:4d}  ({categories[c]/n*100:5.1f}%)")

    print("\n── Failure Reason Code Distribution ──")
    for r in sorted(reasons, key=reasons.get, reverse=True):
        print(f"  {r:25s} {reasons[r]:4d}  ({reasons[r]/n*100:5.1f}%)")

    print("\n── Pre-Debit Notification ──")
    print(f"  Sent:     {notif[True]:4d}  ({notif[True]/n*100:.1f}%)")
    print(f"  Not sent: {notif[False]:4d}  ({notif[False]/n*100:.1f}%)")

    print("\n── AFA Threshold (category-aware) ──")
    above = sum(1 for r in records if r["amount_above_afa_threshold"])
    print(f"  Above threshold: {above:4d}  ({above/n*100:.1f}%)")
    for cat in sorted(set(r["payment_category"] for r in records)):
        cat_recs = [r for r in records if r["payment_category"] == cat]
        cat_above = sum(1 for r in cat_recs if r["amount_above_afa_threshold"])
        threshold = AFA_THRESHOLDS[cat]
        print(f"    {cat:15s} (₹{threshold:,} threshold): {cat_above}/{len(cat_recs)} above")

    print("\n── Bank Outage Cluster Verification ──")
    outage_recs = [r for r in records if r["ground_truth_cause"] == "bank_outage"]
    by_bank = {}
    for r in sorted(outage_recs, key=lambda r: (r["bank_name"], r["failure_timestamp"])):
        by_bank.setdefault(r["bank_name"], []).append(r)
    for bank, recs in sorted(by_bank.items(), key=lambda x: -len(x[1])):
        print(f"  {bank}: {len(recs)} outage records")
        timestamps = sorted(datetime.fromisoformat(r["failure_timestamp"]) for r in recs)
        if len(timestamps) >= 2:
            span = timestamps[-1] - timestamps[0]
            bins_used = set(r["bin"] for r in recs)
            print(f"    Time span: {span}  |  BINs: {', '.join(sorted(bins_used))}")

    # Mandate revoked verification
    revoked = [r for r in records if r["ground_truth_cause"] == "mandate_revoked"]
    if revoked:
        all_after = all(
            r["mandate_expiry_date"] > r["failure_timestamp"][:10]
            for r in revoked if "mandate_expiry_date" in r
        )
        notif_pct = sum(1 for r in revoked if r["pre_debit_notification_sent"]) / len(revoked) * 100
        print(f"\n── Mandate Revoked Verification ──")
        print(f"  Count: {len(revoked)}")
        print(f"  All mandate_expiry_date after failure: {all_after}")
        print(f"  Pre-debit notification sent: {notif_pct:.0f}%")

    edge_indicators = sum(1 for r in records if (
        r["bin"] in ("", "41X") or
        r["customer_prior_success_count"] == 0 and r["customer_prior_failure_count"] == 0 or
        r["amount"] == 15000.00
    ))
    print(f"\n  Edge-case-like records (approx): {edge_indicators}")


if __name__ == "__main__":
    generate()
