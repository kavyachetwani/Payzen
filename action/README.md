# /action — LangGraph Action Router

**Built in: Stage 5**

LangGraph-based action router that dispatches each case to the appropriate recovery action:

- Auto-retry (via Razorpay API)
- Card-update link (send customer a payment method update link)
- Mandate resequence (reschedule the mandate debit)
- Hinglish conversational escalation (hardest/highest-value cases only — routes to /voice)

Every action is gated behind human-in-the-loop approval with compliance checks.
