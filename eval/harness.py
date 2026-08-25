"""The evaluation harness.

Runs a batch of mandates through a policy, writing every decision to the audit log and every attempt
outcome to the metrics pipeline. Knows nothing about which policy it is running -- it only knows the
`Policy` contract.

The simulation loop is deliberately simple: a mandate fails once, the policy decides, and if it
schedules a retry the harness evaluates whether that retry would have succeeded given ground truth at
that moment. Repeat until recovery, the attempt cap, or an unrecoverable stop.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from audit.decision_log_schema.records import (
    DecisionLog,
    DecisionRecord,
    DecisionType,
    Source,
)
from compliance.invariants.rules import ProposedDecision, evaluate_all
from eval.metrics.definitions import AttemptOutcome, MandateOutcome
from policies.policy_interface.base import Policy, PolicyState
from simulator.balance_evolution.process import simulate_balance
from simulator.failure_events.generators import AttemptContext, success_probability
from simulator.mandate import UNRECOVERABLE_CLASSES, FailureClass, Mandate

HORIZON_DAYS = 90

# Which failure class a given mandate hits. Not sourced -- there is no public distribution of failure
# classes across Indian recurring payments (that would be exactly the proprietary data this project
# is built to work without). Insufficient funds dominates, consistent with the one aggregate signal
# we do have: ~20M monthly UPI Autopay revocations attributed to low balance (A9).
FAILURE_CLASS_WEIGHTS = {
    FailureClass.INSUFFICIENT_FUNDS: 0.55,
    FailureClass.NPCI_CONGESTION: 0.15,
    FailureClass.NOTIFICATION_UNDELIVERED: 0.10,
    FailureClass.BANK_TECHNICAL_DECLINE: 0.10,
    FailureClass.MANDATE_EXPIRED: 0.05,
    FailureClass.MANDATE_REVOKED: 0.05,
}


@dataclass
class RunResult:
    policy_name: str
    mandate_outcomes: list[MandateOutcome]
    attempt_outcomes: list[AttemptOutcome]
    decision_log: DecisionLog


def _assign_failure_class(rng: np.random.Generator) -> FailureClass:
    classes = list(FAILURE_CLASS_WEIGHTS.keys())
    weights = np.array(list(FAILURE_CLASS_WEIGHTS.values()))
    return classes[rng.choice(len(classes), p=weights / weights.sum())]


def _first_consistent_failure_day(
    failure_class: FailureClass,
    mandate: Mandate,
    trajectory,
    rng: np.random.Generator,
) -> int:
    """Picks a first-failure day on which the assigned failure class is actually *true*.

    Without this the simulation is internally incoherent: a mandate labelled an insufficient-funds
    failure whose balance comfortably covers the amount didn't actually fail for that reason. The
    first version picked the failure day uniformly at random, which meant most insufficient-funds
    mandates were "failing" while flush -- and then trivially recovering on the next-day retry.

    Anchoring the failure to a day when its cause holds is a correctness fix, not a tuning knob:
    it makes the world self-consistent. No policy exists to tune toward yet.
    """
    if failure_class == FailureClass.INSUFFICIENT_FUNDS:
        short_days = [
            d for d in range(min(30, len(trajectory.daily_balance_inr)))
            if trajectory.balance_on(d) < mandate.amount_inr
        ]
        if short_days:
            return int(rng.choice(short_days))
        # Balance never dips below the amount in the window: this customer wouldn't fail this way.
        # Fall through to an arbitrary early day rather than silently forcing an impossible failure.
        return int(rng.integers(0, 10))

    if failure_class == FailureClass.MANDATE_EXPIRED:
        # Expiry failures happen at/after expiry, by definition (A19).
        return int(min(mandate.validity_days, HORIZON_DAYS - 1))

    if failure_class == FailureClass.NPCI_CONGESTION:
        return int(rng.integers(0, 10))

    return int(rng.integers(0, 10))


def run_policy_on_batch(
    policy: Policy,
    mandates: list[Mandate],
    config: dict,
    seed: int,
) -> RunResult:
    rng = np.random.default_rng(seed)
    log = DecisionLog()
    mandate_outcomes: list[MandateOutcome] = []
    attempt_outcomes: list[AttemptOutcome] = []

    max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]
    delivery_failure_rate_range = config["failure_classes"]["notification_undelivered"][
        "delivery_failure_rate"
    ]["range"]

    for mandate in mandates:
        failure_class = _assign_failure_class(rng)
        trajectory = simulate_balance(
            mandate_amount_inr=mandate.amount_inr,
            timing_type=mandate.income_timing_type,
            horizon_days=HORIZON_DAYS,
            config=config,
            rng=rng,
        )

        first_failure_day = _first_consistent_failure_day(
            failure_class, mandate, trajectory, rng
        )
        current_time = mandate.created_at + timedelta(days=first_failure_day)
        attempt_number = 1
        consecutive_failures = 1
        recovered = False
        days_to_recovery: float | None = None
        notification_sent_at: datetime | None = None

        while attempt_number <= max_attempts:
            state = PolicyState(
                mandate=mandate,
                failure_class=failure_class,
                attempt_number=attempt_number,
                failed_at=current_time,
                consecutive_failures=consecutive_failures,
                notification_sent_at=notification_sent_at,
            )
            decision = policy.decide(state, config)

            proposed = ProposedDecision(
                mandate_id=mandate.mandate_id,
                amount_inr=mandate.amount_inr,
                scheduled_retry_at=decision.scheduled_retry_at,
                notification_sent_at=decision.notification_to_send_at or notification_sent_at,
            )
            checks = evaluate_all(proposed, config)
            compliant = all(c.passed for c in checks)

            # The veto. A compliance floor that is logged but not enforced is not a floor -- the
            # harness refuses to execute a non-compliant retry regardless of what the policy wanted.
            # The proposal is still recorded, so a policy that repeatedly proposes illegal actions
            # is visible in the audit trail rather than quietly corrected.
            blocked = decision.decision_type == DecisionType.RETRY_SCHEDULED and not compliant
            recorded_type = (
                DecisionType.BLOCKED_BY_COMPLIANCE if blocked else decision.decision_type
            )

            log.append(
                DecisionRecord(
                    decision_id=f"{policy.name}_{mandate.mandate_id}_{attempt_number}",
                    mandate_id=mandate.mandate_id,
                    policy_name=policy.name,
                    decision_type=recorded_type,
                    rule_id=decision.rule_id,
                    rule_description=decision.rule_description,
                    failure_class=failure_class.value,
                    attempt_number=attempt_number,
                    decided_at=current_time,
                    source=Source.SIMULATION,
                    scheduled_retry_at=decision.scheduled_retry_at,
                    escalation_action=decision.escalation_action,
                    compliance_checks=checks,
                    amount_inr=mandate.amount_inr,
                    metadata={"proposed_decision_type": decision.decision_type.value} if blocked else {},
                )
            )

            if blocked or decision.decision_type != DecisionType.RETRY_SCHEDULED:
                break

            retry_at = decision.scheduled_retry_at
            assert retry_at is not None
            if decision.notification_to_send_at is not None:
                notification_sent_at = decision.notification_to_send_at

            day_index = (retry_at - mandate.created_at).days
            notification_delivered = bool(
                rng.uniform() > rng.uniform(*delivery_failure_rate_range)
            )

            ctx = AttemptContext(
                mandate=mandate,
                attempt_time=retry_at,
                day_index=day_index,
                balance_inr=trajectory.balance_on(day_index),
                notification_delivered=notification_delivered,
                consecutive_failures=consecutive_failures,
            )
            p_success = success_probability(failure_class, ctx, config, rng)
            succeeded = bool(rng.uniform() < p_success)

            attempt_outcomes.append(
                AttemptOutcome(
                    mandate_id=mandate.mandate_id,
                    amount_inr=mandate.amount_inr,
                    succeeded=succeeded,
                    true_success_probability=p_success,
                    is_recoverable_class=failure_class not in UNRECOVERABLE_CLASSES,
                )
            )

            current_time = retry_at
            if succeeded:
                recovered = True
                days_to_recovery = (retry_at - mandate.created_at).days - first_failure_day
                break

            attempt_number += 1
            consecutive_failures += 1

        mandate_outcomes.append(
            MandateOutcome(
                mandate_id=mandate.mandate_id,
                amount_inr=mandate.amount_inr,
                recovered=recovered,
                is_recoverable_class=failure_class not in UNRECOVERABLE_CLASSES,
                attempts_made=attempt_number - 1 if recovered else attempt_number,
                days_to_recovery=float(days_to_recovery) if days_to_recovery is not None else None,
            )
        )

    return RunResult(
        policy_name=policy.name,
        mandate_outcomes=mandate_outcomes,
        attempt_outcomes=attempt_outcomes,
        decision_log=log,
    )
