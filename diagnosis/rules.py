"""SQL-based diagnosis rules for failed recurring payments.

Each rule queries the normalized tables (NEVER ground_truth) and returns a
(cause_label, confidence) pair. Rules are applied in priority order; the first
match wins.

All configurable parameters are in DEFAULT_CONFIG at the top of this file.
"""

import sqlite3

DEFAULT_CONFIG = {
    "bin_prefix_length": 4,
    "cluster_time_window_hours": 2.0,
    "cluster_count_threshold": 5,
}


def diagnose(payment_id: str, conn: sqlite3.Connection,
             config: dict | None = None) -> dict:
    cfg = config or DEFAULT_CONFIG

    row = conn.execute("""
        SELECT p.*, c.prior_success_count, c.prior_failure_count
        FROM payments p
        JOIN customers c ON p.customer_id = c.customer_id
        WHERE p.payment_id = ?
    """, (payment_id,)).fetchone()

    if row is None:
        return {"payment_id": payment_id, "diagnosed_cause": "unknown", "confidence": 0.0}

    reason = row["failure_reason_code"]
    method = row["payment_method"]
    amount_above = row["amount_above_afa_threshold"]
    ts = row["failure_timestamp"]
    raw_bin = row["bin"]
    prior_success = row["prior_success_count"]
    prior_failure = row["prior_failure_count"]
    mandate_expiry = row["mandate_expiry_date"]

    prefix_len = cfg["bin_prefix_length"]
    bin_prefix = raw_bin[:prefix_len] if len(raw_bin) >= prefix_len else ""

    # Rule 1: Mandate expired
    if reason == "14" and mandate_expiry and mandate_expiry < ts[:10]:
        return _result(payment_id, "mandate_expired", 0.95)

    # Rule 2: Mandate revoked
    if reason == "61":
        return _result(payment_id, "mandate_revoked", 0.90)

    # Rule 3: Card expired
    if reason == "card_expired" and method == "card_auto_debit":
        return _result(payment_id, "card_expired", 0.90)

    # Rule 4: Bank outage (BIN cluster detection)
    if bin_prefix:
        window = cfg["cluster_time_window_hours"]
        threshold = cfg["cluster_count_threshold"]

        cluster_count = conn.execute("""
            SELECT COUNT(*) FROM payments
            WHERE substr(bin, 1, ?) = ?
              AND ABS(julianday(failure_timestamp) - julianday(?)) * 24 < ?
              AND payment_id != ?
        """, (prefix_len, bin_prefix, ts, window, payment_id)).fetchone()[0]

        if cluster_count >= threshold:
            if cluster_count >= threshold * 2:
                conf = 0.90
            elif cluster_count >= int(threshold * 1.5):
                conf = 0.80
            else:
                conf = 0.70
            return _result(payment_id, "bank_outage", conf)

    # Rule 5: AFA stuck
    if reason in ("afa_pending", "timeout", "unknown") and amount_above:
        conf = 0.80 if reason == "afa_pending" else 0.60
        return _result(payment_id, "afa_stuck", conf)

    # Rule 6: Insufficient funds
    if reason == "04":
        return _result(payment_id, "insufficient_funds", 0.85)
    if prior_success + prior_failure > 0 and prior_failure > prior_success:
        return _result(payment_id, "insufficient_funds", 0.55)

    # Rule 7: Ambiguous fallback
    return _result(payment_id, "ambiguous", 0.30)


def _result(payment_id, cause, confidence):
    return {"payment_id": payment_id, "diagnosed_cause": cause, "confidence": confidence}


def diagnose_all(conn: sqlite3.Connection, config: dict | None = None,
                 payment_ids: list[str] | None = None) -> list[dict]:
    if payment_ids is None:
        rows = conn.execute("SELECT payment_id FROM payments ORDER BY payment_id").fetchall()
        payment_ids = [r["payment_id"] for r in rows]
    return [diagnose(pid, conn, config) for pid in payment_ids]
