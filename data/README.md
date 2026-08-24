# /data — Synthetic Data Generation

**Built in: Stage 2**

This directory will contain scripts to generate synthetic datasets:

- **Payment failure dataset** (300–500 records): simulated UPI Autopay / eNACH failures with
  realistic failure codes, BINs, mandate details, timestamps, and amounts.
- **Retry outcome dataset** (300–500 records): historical retry attempts with outcomes, used to
  train the contextual bandit.

All data is synthetic — no real customer or payment data is used anywhere in this project.
