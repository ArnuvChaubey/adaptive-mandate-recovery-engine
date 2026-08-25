"""Baseline policy -- documented halt condition, conservatively-assumed cadence.

**Naming honesty (see A1, A2).** This is not "Razorpay's retry policy." Only the halt condition is
documented: after 4 failed attempts a subscription moves to `halted`. The *spacing* between those
attempts is not published anywhere for cards or UPI -- the docs say only "We automatically retry the
payment on the following day."

So the cadence here is an ASSUMPTION, and it is deliberately biased toward the most retry-friendly
plausible interval (retry next day, every time). If that assumption is wrong, the error makes the
baseline *stronger* than reality, which makes any measured adaptive lift harder to achieve rather
than easier. Erring in the direction that hurts our own headline number is the point.

This policy ignores failure class, time of day, notification state, and balance -- it retries on a
fixed schedule until the cap. That is precisely the behaviour Razorpay's own Intelligent Retry Engine
materials describe as "rigid" (see docs/positioning.md).
"""

from datetime import timedelta

from audit.decision_log_schema.records import DecisionType, EscalationAction
from policies.policy_interface.base import Decision, Policy, PolicyState
from simulator.mandate import UNRECOVERABLE_CLASSES, FailureClass

RULE_FIXED_RETRY = "BASE-001"
RULE_ATTEMPTS_EXHAUSTED = "BASE-002"
RULE_UNRECOVERABLE = "BASE-003"


class BaselinePolicy(Policy):
    name = "baseline"

    def decide(self, state: PolicyState, config: dict) -> Decision:
        max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]

        # Even a fixed-schedule baseline must stop on an unrecoverable failure -- retrying a revoked
        # mandate isn't a policy choice, there is no authorization to charge against (A19).
        if state.failure_class in UNRECOVERABLE_CLASSES:
            return Decision(
                decision_type=DecisionType.STOPPED_UNRECOVERABLE,
                rule_id=RULE_UNRECOVERABLE,
                rule_description=(
                    f"{state.failure_class.value} cannot be recovered by any retry timing; stop and escalate"
                ),
                escalation_action=(
                    EscalationAction.REQUEST_REMANDATE
                    if state.failure_class == FailureClass.MANDATE_EXPIRED
                    else EscalationAction.NO_ACTION_POSSIBLE
                ),
            )

        if state.attempt_number >= max_attempts:
            return Decision(
                decision_type=DecisionType.STOPPED_ATTEMPTS_EXHAUSTED,
                rule_id=RULE_ATTEMPTS_EXHAUSTED,
                rule_description=(
                    f"Attempt cap of {max_attempts} reached (Razorpay documented halt condition); stop and escalate"
                ),
                escalation_action=EscalationAction.NOTIFY_CUSTOMER_MANUAL_PAYMENT,
            )

        cadence_days = config["retry_policy_shared"]["card_retry_cadence_days"]["value"]
        gap_days = cadence_days[min(state.attempt_number - 1, len(cadence_days) - 1)]
        retry_at = state.failed_at + timedelta(days=gap_days)

        # A pre-transaction notification must precede the debit by 24h (A5, RBI Clause 6(a)). The
        # baseline satisfies this mechanically rather than strategically: send it as soon as the
        # failure happens, then retry on the fixed schedule.
        min_hours = config["failure_classes"]["notification_undelivered"][
            "min_hours_between_notification_and_debit"
        ]["value"]
        notification_at = state.failed_at
        if retry_at - notification_at < timedelta(hours=min_hours):
            retry_at = notification_at + timedelta(hours=min_hours)

        return Decision(
            decision_type=DecisionType.RETRY_SCHEDULED,
            rule_id=RULE_FIXED_RETRY,
            rule_description=(
                f"Fixed cadence: retry {gap_days} day(s) after failure, regardless of failure class "
                f"or timing (attempt {state.attempt_number} of {max_attempts})"
            ),
            scheduled_retry_at=retry_at,
            notification_to_send_at=notification_at,
        )
