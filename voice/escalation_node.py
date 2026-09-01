"""LangGraph-compatible escalation node for mandate_revoked payments.

Replaces the simple escalation_node in action/nodes.py for mandate_revoked
cases. Instead of just logging "escalated to human review", this node
initializes an escalation conversation that the merchant can drive from
the dashboard chat widget.
"""

from voice.escalation_agent import EscalationAgent
from voice.customer_simulator import CustomerSimulator

_agent_instance: EscalationAgent | None = None


def get_agent(brand_name: str = "YourBrand") -> EscalationAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = EscalationAgent(brand_name=brand_name)
    return _agent_instance


def reset_agent():
    global _agent_instance
    _agent_instance = None


def escalation_conversation_node(state: dict) -> dict:
    """LangGraph node: start an escalation conversation for mandate_revoked."""
    cause = state["diagnosis"]["cause"]
    payment_id = state["payment_id"]
    customer_id = state["customer_id"]
    amount = state["amount"]
    category = state.get("payment_record", {}).get("payment_category", "")

    agent = get_agent()

    if cause == "mandate_revoked":
        result = agent.start_conversation(
            payment_id=payment_id,
            customer_id=customer_id,
            amount=amount,
            payment_category=category,
        )

        outcome = {
            "success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "details": f"escalation conversation started — greeting sent",
            "conversation_state": result["state"],
        }
    else:
        outcome = {
            "success": False,
            "amount_recovered": 0.0,
            "action_cost": 0.0,
            "details": f"escalated to human review — cause: {cause}",
        }

    audit = {
        "payment_id": payment_id,
        "customer_id": customer_id,
        "cause": cause,
        "action_type": "escalation",
        "action_node": "escalation",
        "success": False,
        "amount_recovered": 0.0,
        "action_cost": 0.0,
        "escalation_reason": f"mandate_revoked — conversation initiated" if cause == "mandate_revoked" else f"escalated: {cause}",
    }

    return {"action_outcome": outcome, "audit_entry": audit}


def run_escalation(payment_id: str = "PAY_TEST", use_model: bool = True,
                   scenario: str = "too_expensive", amount: float = 15000,
                   personality: str = "hesitant", seed: int = 42) -> dict:
    """Run a full escalation conversation with the customer simulator."""
    agent = EscalationAgent(brand_name="Customer Demo Store", use_llm=use_model)
    simulator = CustomerSimulator(scenario, personality, amount, seed)

    result = agent.start_conversation(
        payment_id=payment_id,
        customer_id="CUST_TEST",
        amount=amount,
        payment_category="emi",
    )

    transcript = [{"role": "agent", "text": result["agent_message"]}]

    for _ in range(5):
        if result.get("conversation_ended"):
            break
        customer_msg = simulator.respond(result["agent_message"])
        transcript.append({"role": "customer", "text": customer_msg})
        result = agent.process_customer_message(payment_id, customer_msg)
        transcript.append({"role": "agent", "text": result["agent_message"]})

    return {
        "transcript": transcript,
        "outcome": result["state"]["outcome"],
        "scenario": result["state"]["scenario"],
        "turn_count": result["state"]["turn_count"],
    }
