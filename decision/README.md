# /decision — Contextual Bandit + Optuna Tuning

**Built in: Stage 4**

Optuna-tuned contextual bandit that decides WHEN and HOW to retry failed payments.
No LLM involved — pure optimization.

- Reward function: net ₹ recovered (amount recovered minus action cost)
- Arms: auto-retry, card-update-link, mandate-resequence, escalation
- Tuning: Optuna hyperparameter search over bandit parameters
