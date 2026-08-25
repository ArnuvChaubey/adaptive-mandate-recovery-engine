"""Deterministic narration. No LLM.

This is the *primary* narration path, not a fallback. Every sentence it produces is assembled from
structured fields already present in the decision record, so it cannot invent a reason, a rupee
amount, or a regulation.

The LLM layer (llm_explainer/) sits on top and rewrites these into more fluent prose. It adds
readability, never facts -- and if it is unavailable, misconfigured, or fails validation, the system
degrades to exactly this output rather than to nothing.

That split is the deliberate answer to Track 03's "AI judgment" criterion: the right tool in the
right place, and a visible decision about where *not* to use one.
"""

from audit.decision_log_schema.records import DecisionRecord, DecisionType, EscalationAction

_FAILURE_CLASS_PLAIN_ENGLISH = {
    "insufficient_funds": "there wasn't enough balance in the account at the time of the debit",
    "notification_undelivered": "the required pre-debit notification didn't reach the customer",
    "npci_congestion": "the payment network was deprioritising automated mandates at that hour",
    "bank_technical_decline": "the bank declined the debit for a temporary technical reason",
    "mandate_expired": "the mandate's authorisation period had already ended",
    "mandate_revoked": "the customer had cancelled the mandate",
}

_ESCALATION_PLAIN_ENGLISH = {
    EscalationAction.REQUEST_REMANDATE: (
        "ask the customer to set up a fresh mandate",
        "Your automatic payment authorisation has expired. To continue your subscription without "
        "interruption, please set up a new payment mandate.",
    ),
    EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION: (
        "ask the customer to authorise this payment directly",
        "This payment is above the limit for automatic processing, so it needs your approval. "
        "Please authorise the payment to keep your subscription active.",
    ),
    EscalationAction.NOTIFY_CUSTOMER_MANUAL_PAYMENT: (
        "ask the customer to pay manually",
        "We were unable to collect your payment automatically. Please complete the payment manually "
        "to keep your subscription active.",
    ),
    EscalationAction.NO_ACTION_POSSIBLE: (
        "take no further action -- the customer has withdrawn consent",
        "",  # deliberately empty: messaging a customer who cancelled is not a compliant action
    ),
}


def internal_explanation(record: DecisionRecord) -> str:
    """One paragraph for an operator or auditor reading the decision log."""
    cause = _FAILURE_CLASS_PLAIN_ENGLISH.get(
        record.failure_class, f"the payment failed ({record.failure_class})"
    )
    lines = [
        f"Attempt {record.attempt_number} on mandate {record.mandate_id} "
        f"(INR {record.amount_inr:,.2f}) failed because {cause}."
    ]

    if record.decision_type == DecisionType.RETRY_SCHEDULED and record.scheduled_retry_at:
        lines.append(
            f"Rule {record.rule_id} scheduled the next attempt for "
            f"{record.scheduled_retry_at:%Y-%m-%d %H:%M}. Reason given: {record.rule_description}"
        )
    elif record.decision_type == DecisionType.BLOCKED_BY_COMPLIANCE:
        failed = [c for c in record.compliance_checks if not c.passed]
        detail = "; ".join(f"{c.invariant_id}: {c.detail}" for c in failed)
        lines.append(
            f"Rule {record.rule_id} proposed a retry, but it was blocked before execution "
            f"because it breached a compliance floor ({detail})."
        )
    else:
        action_text = (
            _ESCALATION_PLAIN_ENGLISH[record.escalation_action][0]
            if record.escalation_action
            else "stop"
        )
        lines.append(
            f"Rule {record.rule_id} stopped further automatic attempts and the next step is to "
            f"{action_text}. Reason given: {record.rule_description}"
        )

    # Only rules that actually applied to this decision. A rule that didn't apply is not a rule
    # that was satisfied, and reporting it as such makes the audit trail read misleadingly.
    satisfied = [c for c in record.compliance_checks if c.passed and c.applicable]
    if satisfied:
        lines.append(
            "Compliance checks satisfied: " + ", ".join(c.invariant_id for c in satisfied) + "."
        )
    return " ".join(lines)


def customer_message(record: DecisionRecord) -> str:
    """Draft customer-facing message, or empty when contacting the customer isn't appropriate.

    Deliberately conservative: no promises about when money will be taken, no invented offers, and
    nothing for a customer who has already revoked their mandate.
    """
    if record.decision_type == DecisionType.RETRY_SCHEDULED and record.scheduled_retry_at:
        return (
            "We couldn't collect your subscription payment this time. "
            f"We'll try again on {record.scheduled_retry_at:%d %b %Y}. "
            "To avoid any interruption, please make sure your account has sufficient balance."
        )
    if record.escalation_action is not None:
        return _ESCALATION_PLAIN_ENGLISH[record.escalation_action][1]
    return ""
