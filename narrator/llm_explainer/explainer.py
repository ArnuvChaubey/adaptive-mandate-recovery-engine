"""LLM narration layer.

Reads decision-log records. Writes prose. Never touches policy state, never feeds anything back into
a decision, and cannot run before a decision has already been made and logged.

Everything it emits passes through narrator.validator first. Output that introduces a number,
a date, or a claim the record doesn't support is discarded and the deterministic template is used
instead -- so a hallucination degrades fluency, never correctness.
"""

import os
from dataclasses import dataclass

from audit.decision_log_schema.records import DecisionRecord
from narrator import templates
from narrator.validator import ValidationResult, validate

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You rewrite payment-recovery decision records into clear prose for an Indian \
fintech operating under RBI e-mandate rules.

You are a NARRATOR, not a decision-maker. The decision has already been made by a deterministic \
policy engine and recorded in an audit log. Your job is to describe what was decided and why, in \
language a person can read. You never evaluate whether the decision was correct and you never \
suggest an alternative.

Hard rules:
- Use ONLY facts present in the record you are given. Never introduce an amount, a date, a rate, a \
deadline, or a regulation that is not in the record.
- Always cite the rule identifier from the record verbatim in the internal explanation.
- Never promise an outcome, threaten a consequence, or mention refunds, penalties, legal action, or \
credit scores.
- If the record indicates no customer contact is appropriate, return an empty customer message.

Return exactly two sections, in this format and nothing else:

INTERNAL: <two or three sentences for an operations analyst or auditor>
CUSTOMER: <one or two sentences addressed to the customer, or the single word NONE>"""


@dataclass(frozen=True)
class Narration:
    internal_explanation: str
    customer_message: str
    source: str                      # "llm" or "template"
    validation: ValidationResult | None
    # Always false. Present in the output schema so that anyone reading a narration -- in a report,
    # a demo, or a JSON dump -- can see at a glance that it had no influence on the decision.
    influenced_decision: bool = False


def _render_record(record: DecisionRecord) -> str:
    lines = [
        f"rule_id: {record.rule_id}",
        f"rule_description: {record.rule_description}",
        f"decision_type: {record.decision_type.value}",
        f"failure_class: {record.failure_class}",
        f"attempt_number: {record.attempt_number}",
        f"amount_inr: {record.amount_inr:,.2f}",
        f"decided_at: {record.decided_at:%Y-%m-%d %H:%M}",
    ]
    if record.scheduled_retry_at:
        lines.append(f"scheduled_retry_at: {record.scheduled_retry_at:%Y-%m-%d %H:%M}")
    if record.escalation_action:
        lines.append(f"escalation_action: {record.escalation_action.value}")
    for check in record.compliance_checks:
        status = "PASSED" if check.passed else "FAILED"
        lines.append(f"compliance_check: {check.invariant_id} {status} -- {check.detail}")
    return "\n".join(lines)


def _parse(response_text: str) -> tuple[str, str]:
    internal, customer = "", ""
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("INTERNAL:"):
            internal = stripped[len("INTERNAL:"):].strip()
        elif stripped.upper().startswith("CUSTOMER:"):
            customer = stripped[len("CUSTOMER:"):].strip()
    if customer.strip().upper() == "NONE":
        customer = ""
    return internal, customer


def narrate_with_template(record: DecisionRecord) -> Narration:
    return Narration(
        internal_explanation=templates.internal_explanation(record),
        customer_message=templates.customer_message(record),
        source="template",
        validation=None,
    )


def narrate(record: DecisionRecord, client=None) -> Narration:
    """Narrate one decision, preferring the LLM and falling back to the template.

    Falls back silently and safely when: no API key is configured, the SDK isn't installed, the call
    fails, or the output fails grounding validation. The system is fully functional with the LLM
    layer removed entirely -- which is the point.
    """
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return narrate_with_template(record)
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception:
            return narrate_with_template(record)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            # A structured-summarisation task with strict grounding rules -- low effort is the right
            # setting. Reasoning depth is not the bottleneck here; obedience to the record is.
            output_config={"effort": "low"},
            messages=[{
                "role": "user",
                "content": f"Decision record:\n\n{_render_record(record)}",
            }],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
    except Exception:
        return narrate_with_template(record)

    # Truncation check. A response cut off at max_tokens can still be perfectly *grounded* -- every
    # number in it came from the record -- so the validator will happily pass it. It caught a real
    # case where the internal explanation ended mid-word and the CUSTOMER line was lost entirely,
    # silently turning an escalation that needed customer contact into one with no message at all.
    # Guarding against invention is not the same as guarding against omission.
    if getattr(response, "stop_reason", None) == "max_tokens":
        return narrate_with_template(record)

    internal, customer = _parse(text)
    if not internal:
        return narrate_with_template(record)

    # Completeness: a decision whose escalation calls for contacting the customer must produce a
    # customer message. Silence here is a dropped obligation, not a valid narration.
    if templates.customer_message(record) and not customer:
        return narrate_with_template(record)

    result = validate(internal + " " + customer, record)
    if not result.passed:
        # Ungrounded output is discarded, not repaired. A narration that invents a figure in a
        # payments context is worse than a plain one.
        fallback = narrate_with_template(record)
        return Narration(
            internal_explanation=fallback.internal_explanation,
            customer_message=fallback.customer_message,
            source="template",
            validation=result,
        )

    return Narration(
        internal_explanation=internal,
        customer_message=customer,
        source="llm",
        validation=result,
    )
