"""FastAPI backend for the AI Revenue Recovery dashboard.

Endpoints:
- POST /api/run-batch           — run batch processing (tiered approval)
- GET  /api/overview            — live headline metrics
- GET  /api/decisions           — Tier 3 business decisions pending merchant review
- POST /api/decisions/{id}/approve — approve a business decision
- POST /api/decisions/{id}/reject  — reject a business decision (mark churned)
- GET  /api/activity            — recent activity feed
- GET  /api/config              — current merchant config
- POST /api/config              — update merchant config
- GET  /api/payments            — all payments with filters
- GET  /api/payments/{id}       — detail view for one payment

Legacy (backwards compat):
- GET  /api/pending             — alias for /api/decisions
- POST /api/approve/{id}       — alias for decisions approve
- POST /api/reject/{id}        — alias for decisions reject
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.pipeline import PipelineServer

app = FastAPI(title="AI Revenue Recovery", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = PipelineServer()


class ConfigUpdate(BaseModel):
    sms_enabled: bool | None = None
    calls_enabled: bool | None = None
    call_min_amount: int | None = None
    sms_template: str | None = None
    call_tone: str | None = None
    brand_name: str | None = None
    auto_escalate: bool | None = None
    max_discount_percent: int | None = None


class DecisionResponse(BaseModel):
    response: str = "approve_conversation"


# ── Batch ──

@app.post("/api/run-batch")
def run_batch():
    counts = pipeline.run_batch()
    return counts


# ── Overview ──

@app.get("/api/overview")
def get_overview():
    return pipeline.get_overview()


# ── Tier 3 Business Decisions ──

@app.get("/api/decisions")
def get_decisions():
    return pipeline.get_decisions()


@app.post("/api/decisions/{payment_id}/approve")
def approve_decision(payment_id: str, body: DecisionResponse | None = None):
    response = body.response if body else "approve_conversation"
    return pipeline.approve_decision(payment_id, response=response)


@app.post("/api/decisions/{payment_id}/reject")
def reject_decision(payment_id: str):
    return pipeline.reject_decision(payment_id)


# ── Activity Feed ──

@app.get("/api/activity")
def get_activity(limit: int = Query(50, ge=1, le=500)):
    return pipeline.get_activity(limit=limit)


# ── Merchant Config ──

@app.get("/api/config")
def get_config():
    return pipeline.get_config()


@app.post("/api/config")
def update_config(body: ConfigUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return pipeline.update_config(updates)


# ── Payments ──

@app.get("/api/payments")
def get_payments(
    status: str | None = Query(None),
    cause: str | None = Query(None),
    method: str | None = Query(None),
):
    return pipeline.get_payments(
        status_filter=status,
        cause_filter=cause,
        method_filter=method,
    )


@app.get("/api/payments/{payment_id}")
def get_payment_detail(payment_id: str):
    detail = pipeline.get_payment_detail(payment_id)
    if detail is None:
        return {"error": "not_found", "message": f"Payment {payment_id} not found"}
    return detail


# ── Legacy endpoints (backwards compat) ──

@app.get("/api/pending")
def get_pending():
    return pipeline.get_pending()


@app.post("/api/approve/{payment_id}")
def approve_action(payment_id: str):
    return pipeline.approve_action(payment_id)


@app.post("/api/reject/{payment_id}")
def reject_action(payment_id: str):
    return pipeline.reject_action(payment_id)
