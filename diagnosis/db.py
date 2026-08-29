"""Normalized SQLite schema for the diagnosis layer.

Tables: banks, customers, mandates, payments, ground_truth (evaluation only).
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "payments.db"
DATA_PATH = Path(__file__).parent.parent / "data" / "failed_payments.json"


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS ground_truth;
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS mandates;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS banks;

        CREATE TABLE banks (
            bank_name TEXT PRIMARY KEY,
            bin_prefixes TEXT
        );

        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY,
            prior_success_count INTEGER,
            prior_failure_count INTEGER
        );

        CREATE TABLE mandates (
            mandate_id TEXT PRIMARY KEY,
            customer_id TEXT REFERENCES customers(customer_id),
            expiry_date TEXT
        );

        CREATE TABLE payments (
            payment_id TEXT PRIMARY KEY,
            customer_id TEXT REFERENCES customers(customer_id),
            mandate_id TEXT REFERENCES mandates(mandate_id),
            amount REAL,
            payment_category TEXT,
            payment_method TEXT,
            bank_name TEXT REFERENCES banks(bank_name),
            bin TEXT,
            bin_prefix TEXT,
            failure_timestamp TEXT,
            failure_reason_code TEXT,
            amount_above_afa_threshold INTEGER,
            pre_debit_notification_sent INTEGER,
            mandate_expiry_date TEXT
        );

        CREATE INDEX idx_payments_bin_prefix ON payments(bin_prefix);
        CREATE INDEX idx_payments_timestamp ON payments(failure_timestamp);
        CREATE INDEX idx_payments_reason ON payments(failure_reason_code);

        CREATE TABLE ground_truth (
            payment_id TEXT PRIMARY KEY REFERENCES payments(payment_id),
            cause TEXT
        );
    """)


def load_data(conn: sqlite3.Connection, data_path: str | Path = DATA_PATH) -> int:
    records = json.loads(Path(data_path).read_text())

    banks = {}
    customers = {}
    mandates = {}

    for r in records:
        bname = r["bank_name"]
        if bname not in banks:
            banks[bname] = set()
        if len(r["bin"]) >= 4:
            banks[bname].add(r["bin"][:4])

        cid = r["customer_id"]
        customers[cid] = (r["customer_prior_success_count"], r["customer_prior_failure_count"])

        mid = r["mandate_id"]
        mandates[mid] = (r["customer_id"], r.get("mandate_expiry_date", ""))

    conn.executemany(
        "INSERT OR REPLACE INTO banks VALUES (?, ?)",
        [(name, ",".join(sorted(prefixes))) for name, prefixes in banks.items()],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO customers VALUES (?, ?, ?)",
        [(cid, sc, fc) for cid, (sc, fc) in customers.items()],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO mandates VALUES (?, ?, ?)",
        [(mid, cid, exp) for mid, (cid, exp) in mandates.items()],
    )

    for r in records:
        raw_bin = r["bin"]
        bin_prefix = raw_bin[:4] if len(raw_bin) >= 4 else ""
        conn.execute(
            """INSERT OR REPLACE INTO payments VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["payment_id"], r["customer_id"], r["mandate_id"],
                r["amount"], r["payment_category"], r["payment_method"],
                r["bank_name"], raw_bin, bin_prefix,
                r["failure_timestamp"], r["failure_reason_code"],
                int(r["amount_above_afa_threshold"]),
                int(r["pre_debit_notification_sent"]),
                r.get("mandate_expiry_date", ""),
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO ground_truth VALUES (?, ?)",
            (r["payment_id"], r["ground_truth_cause"]),
        )

    conn.commit()
    return len(records)


def build_db(records: list[dict], db_path: str = ":memory:") -> sqlite3.Connection:
    """Build an in-memory (or on-disk) DB from a list of record dicts."""
    conn = get_connection(db_path)
    create_schema(conn)
    _load_records(conn, records)
    return conn


def _load_records(conn: sqlite3.Connection, records: list[dict]) -> int:
    banks = {}
    customers = {}
    mandates = {}

    for r in records:
        bname = r.get("bank_name", "UNKNOWN")
        if bname not in banks:
            banks[bname] = set()
        raw_bin = r.get("bin", "")
        if len(raw_bin) >= 4:
            banks[bname].add(raw_bin[:4])

        cid = r.get("customer_id", "")
        customers[cid] = (r.get("customer_prior_success_count", 0),
                          r.get("customer_prior_failure_count", 0))

        mid = r.get("mandate_id", f"M_{r.get('payment_id', '')}")
        mandates[mid] = (cid, r.get("mandate_expiry_date", ""))

    conn.executemany(
        "INSERT OR REPLACE INTO banks VALUES (?, ?)",
        [(name, ",".join(sorted(prefixes))) for name, prefixes in banks.items()],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO customers VALUES (?, ?, ?)",
        [(cid, sc, fc) for cid, (sc, fc) in customers.items()],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO mandates VALUES (?, ?, ?)",
        [(mid, cid, exp) for mid, (cid, exp) in mandates.items()],
    )

    for r in records:
        raw_bin = r.get("bin", "")
        bin_prefix = raw_bin[:4] if len(raw_bin) >= 4 else ""
        mid = r.get("mandate_id", f"M_{r.get('payment_id', '')}")
        conn.execute(
            """INSERT OR REPLACE INTO payments VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["payment_id"], r.get("customer_id", ""),
                mid,
                r.get("amount", 0), r.get("payment_category", "emi"),
                r.get("payment_method", "enach"),
                r.get("bank_name", "UNKNOWN"), raw_bin, bin_prefix,
                r.get("failure_timestamp", "2026-01-05T14:30:00"),
                r.get("failure_reason_code", "51"),
                int(r.get("amount_above_afa_threshold", 0)),
                int(r.get("pre_debit_notification_sent", True)),
                r.get("mandate_expiry_date", ""),
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO ground_truth VALUES (?, ?)",
            (r["payment_id"], r.get("ground_truth_cause", "unknown")),
        )

    conn.commit()
    return len(records)


def init_db(db_path: str | Path = DB_PATH, data_path: str | Path = DATA_PATH) -> sqlite3.Connection:
    conn = get_connection(db_path)
    create_schema(conn)
    n = load_data(conn, data_path)
    print(f"Loaded {n} records into {db_path}")
    return conn


if __name__ == "__main__":
    conn = init_db()
    for table in ["banks", "customers", "mandates", "payments", "ground_truth"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")
    conn.close()
