"""FastAPI backend for the AI Revenue Recovery dashboard.

Endpoints:
- POST /api/run-batch     — run Phase 1 batch processing
- GET  /api/overview      — live headline metrics
- GET  /api/pending       — pending actions needing approval
- POST /api/approve/{id}  — approve a pending action
- POST /api/reject/{id}   — reject a pending action
- POST /api/approve-all   — approve all pending actions
- GET  /api/payments      — all payments with filters
- GET  /api/payments/{id} — detail view for one payment
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.pipeline import PipelineServer

app = FastAPI(title="AI Revenue Recovery", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = PipelineServer()


@app.post("/api/run-batch")
def run_batch():
    counts = pipeline.run_batch()
    return counts


@app.get("/api/overview")
def get_overview():
    return pipeline.get_overview()


@app.get("/api/pending")
def get_pending():
    return pipeline.get_pending()


@app.post("/api/approve/{payment_id}")
def approve_action(payment_id: str):
    return pipeline.approve_action(payment_id)


@app.post("/api/reject/{payment_id}")
def reject_action(payment_id: str):
    return pipeline.reject_action(payment_id)


@app.post("/api/approve-all")
def approve_all():
    return pipeline.approve_all()


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
