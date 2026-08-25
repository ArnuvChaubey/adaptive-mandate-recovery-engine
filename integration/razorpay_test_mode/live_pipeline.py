"""Turns a verified Razorpay webhook into a policy decision and an audit record.

This is the closed loop: a real event arrives from Razorpay, the same deterministic policy that runs
against the simulator decides what to do, the same compliance invariants get a veto, and the same
audit schema records it -- tagged `live_test_mode` so it can never be confused with simulated output.

Deliberately a pure function of `(payload, config, policy, attempt_number)` rather than something
wired into the HTTP handler. The receiver stays thin, and this can be tested against the actual
webhook payloads captured from Razorpay on day 2 instead of invented ones.

**Signature verification is the caller's job and is not optional.** Nothing here should ever be
called with a payload whose HMAC has not been checked -- an unverified webhook is attacker-controlled
input, and this function turns input into money decisions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from audit.decision_log_schema.records import (
    DecisionRecord,
    DecisionType,
    EscalationAction,
    Source,
)
from compliance.invariants.rules import ProposedDecision, evaluate_all
from integration.razorpay_test_mode.failure_mapping import map_error_reason
from policies.policy_interface.base import MandateView, Policy, PolicyState
from simulator.mandate import AmountType

# Events that mean "a recovery attempt resolved successfully". No policy decision is needed; the
# money arrived.
RECOVERY_EVENTS = {"payment.captured", "subscription.charged"}

# Events that mean "this mandate is finished and no further automatic attempt is legal".
TERMINAL_EVENTS = {"subscription.halted", "subscription.cancelled"}

# Events that mean "an attempt failed and the policy must decide what happens next".
FAILURE_EVENTS = {"payment.failed", "subscription.pending"}


@dataclass(frozen=True)
class PipelineResult:
    record: DecisionRecord | None
    recovered_amount_inr: float | None = None
    ignored_reason: str | None = None


def _amount_type_for(amount_inr: float) -> AmountType:
    if amount_inr <= 999:
        return AmountType.OTT_SUBSCRIPTION
    if amount_inr <= 25_000:
        return AmountType.SIP_INVESTMENT
    return AmountType.EMI


def _payment_entity(payload: dict[str, Any]) -> dict[str, Any] | None:
    inner = payload.get("payload", {})
    for key in ("payment", "subscription"):
        entity = inner.get(key, {}).get("entity")
        if entity:
            return entity
    return None


def process_event(
    payload: dict[str, Any],
    config: dict,
    policy: Policy,
    attempt_number: int = 1,
) -> PipelineResult:
    """Maps one verified Razorpay webhook to a decision.

    Returns a `PipelineResult` whose `record` is None for events that carry no decision -- a
    successful capture, or an event type this system has no opinion about. Silence is deliberate:
    inventing a decision for an event we don't understand is how a recovery system starts retrying
    things it shouldn't.
    """
    event = payload.get("event")
    entity = _payment_entity(payload)

    if entity is None:
        return PipelineResult(record=None, ignored_reason=f"no payment entity in '{event}'")

    amount_inr = float(entity.get("amount", 0)) / 100.0
    entity_id = entity.get("order_id") or entity.get("id") or "unknown"

    if event in RECOVERY_EVENTS:
        return PipelineResult(record=None, recovered_amount_inr=amount_inr)

    if event in TERMINAL_EVENTS:
        return PipelineResult(
            record=DecisionRecord(
                decision_id=f"live_{entity_id}_terminal",
                mandate_id=entity_id,
                policy_name=policy.name,
                decision_type=DecisionType.STOPPED_UNRECOVERABLE,
                rule_id="LIVE-TERMINAL",
                rule_description=(
                    f"Razorpay reported '{event}'; the mandate is finished and no further automatic "
                    "attempt is available"
                ),
                failure_class="mandate_revoked",
                attempt_number=attempt_number,
                decided_at=datetime.now(),
                source=Source.LIVE_TEST_MODE,
                escalation_action=EscalationAction.NO_ACTION_POSSIBLE,
                compliance_checks=[],
                amount_inr=amount_inr,
                metadata={"razorpay_event": event},
            )
        )

    if event not in FAILURE_EVENTS:
        return PipelineResult(record=None, ignored_reason=f"event '{event}' carries no decision")

    # A real decline code from a real acquirer, mapped through the same table the live batch uses.
    error_reason = entity.get("error_reason")
    failure_class = map_error_reason(error_reason)
    if failure_class is None:
        return PipelineResult(
            record=None,
            ignored_reason=(
                f"decline reason '{error_reason}' is not recoverable by retry timing"
                if error_reason else "no decline reason on a failure event"
            ),
        )

    mandate = MandateView(
        mandate_id=entity_id,
        amount_inr=amount_inr,
        amount_type=_amount_type_for(amount_inr),
        created_at=datetime.fromtimestamp(entity["created_at"]) if entity.get("created_at") else datetime.now(),
        validity_days=365,
    )
    state = PolicyState(
        mandate=mandate,
        failure_class=failure_class,
        attempt_number=attempt_number,
        failed_at=datetime.now(),
        consecutive_failures=attempt_number,
    )
    decision = policy.decide(state, config)

    checks = evaluate_all(
        ProposedDecision(
            mandate_id=mandate.mandate_id,
            amount_inr=amount_inr,
            scheduled_retry_at=decision.scheduled_retry_at,
            notification_sent_at=decision.notification_to_send_at,
        ),
        config,
    )
    blocked = decision.decision_type == DecisionType.RETRY_SCHEDULED and not all(c.passed for c in checks)

    return PipelineResult(record=DecisionRecord(
        decision_id=f"live_{entity_id}_{attempt_number}",
        mandate_id=entity_id,
        policy_name=policy.name,
        decision_type=DecisionType.BLOCKED_BY_COMPLIANCE if blocked else decision.decision_type,
        rule_id=decision.rule_id,
        rule_description=decision.rule_description,
        failure_class=failure_class.value,
        attempt_number=attempt_number,
        decided_at=datetime.now(),
        source=Source.LIVE_TEST_MODE,
        scheduled_retry_at=decision.scheduled_retry_at,
        escalation_action=decision.escalation_action,
        compliance_checks=checks,
        amount_inr=amount_inr,
        metadata={
            "razorpay_event": event,
            "razorpay_error_reason": error_reason,
            "razorpay_error_step": entity.get("error_step"),
            "razorpay_payment_id": entity.get("id"),
        },
    ))
