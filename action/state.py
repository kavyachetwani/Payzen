"""LangGraph state schema for the recovery action pipeline."""

from typing import TypedDict, Any


class PipelineState(TypedDict, total=False):
    payment_id: str
    customer_id: str
    payment_method: str
    amount: float
    payment_record: dict

    diagnosis: dict
    decision: dict
    constraint_result: dict
    gate_result: dict
    action_outcome: dict
    audit_entry: dict
