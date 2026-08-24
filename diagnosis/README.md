# /diagnosis — SQL-Based Diagnosis Layer

**Built in: Stage 3**

SQL-based correlation rules to diagnose WHY a payment failed. No LLM involved.

Rules include:
- Bank-outage clustering by BIN
- Mandate-expiry checks
- AFA-threshold checks
- Low-balance heuristics

Uses SQLAlchemy against a relational database (SQLite or Postgres).
