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
    EscalationAction,
    Source,
)
from compliance.invariants.rules import ProposedDecision, evaluate_all, rbi_category_for
from eval.metrics.definitions import AttemptOutcome, MandateOutcome
from policies.policy_interface.base import MandateView, Policy, PolicyState
from simulator.balance_evolution.process import simulate_balance
from simulator.config_loader import sample_from_range
from simulator.failure_events.generators import AttemptContext, success_probability
from simulator.mandate import UNRECOVERABLE_CLASSES, FailureClass, Mandate

HORIZON_DAYS = 90

# The failure-class distribution now lives in the frozen config (A36), not here. It was hardcoded in
# this module until 2026-08-25, which meant the single most impactful ground-truth parameter in the
# project sat outside the freeze protocol the entire credibility claim rests on, carried no
# assumption ID, and could not be swept. See docs/build_log.md entry 18.


@dataclass
class RunResult:
    policy_name: str
    mandate_outcomes: list[MandateOutcome]
    attempt_outcomes: list[AttemptOutcome]
    decision_log: DecisionLog


def _assign_failure_class(config: dict, rng: np.random.Generator) -> FailureClass:
    mix = config["failure_class_mix"]["weights"]
    classes = [FailureClass(name) for name in mix]
    weights = np.array(list(mix.values()), dtype=float)
    return classes[rng.choice(len(classes), p=weights / weights.sum())]


def _first_failure_hour(failure_class: FailureClass, rng: np.random.Generator) -> int:
    """Time-of-day of the initial failure, consistent with its cause.

    Added after the sensitivity sweep returned byte-identical results for the severe- and
    mild-congestion scenarios. Root cause: every mandate was created at midnight, retries inherited
    that time, and the NPCI window (10:00-13:00) therefore never triggered for anyone. The congestion
    failure class was inert, and the adaptive policy's congestion-avoidance rule was providing
    exactly zero measured value while appearing to work.

    A congestion failure by definition happened *during* the congestion window, so that is when it is
    placed. Other classes are spread across plausible batch-processing hours.
    """
    if failure_class == FailureClass.NPCI_CONGESTION:
        return int(rng.integers(10, 13))
    return int(rng.integers(0, 24))


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
    log = DecisionLog()
    mandate_outcomes: list[MandateOutcome] = []
    attempt_outcomes: list[AttemptOutcome] = []

    max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]
    delivery_failure_rate_range = config["failure_classes"]["notification_undelivered"][
        "delivery_failure_rate"
    ]["range"]

    for mandate_index, mandate in enumerate(mandates):
        # Each mandate gets its own RNG, independent of every other mandate in the batch. This is
        # what makes "the same batch of mandates" a literally true claim across policies rather than
        # an approximation: mandate N's failure class and balance trajectory are drawn from a stream
        # that depends only on (seed, N), never on how many attempts policies before it happened to
        # take. Confirmed broken before this fix -- 30 of 50 mandates got assigned a DIFFERENT
        # failure class between a baseline run and an adaptive run of the "same" seed, because the
        # two policies consumed different numbers of draws per mandate and the single shared stream
        # drifted out of sync after the very first divergence. See docs/build_log.md entry 21.
        #
        # A per-attempt outcome (notification-delivery luck, decline magnitude, the success coinflip
        # itself) is intentionally NOT re-matched across policies beyond this: those draws depend on
        # which day and which attempt number a policy actually chose, and asking "what would the coin
        # flip have been on a day this policy never attempted" isn't a more rigorous question, it's a
        # different one. Matching stops at "what world does this mandate start in" -- which is exactly
        # the boundary the MandateView redaction already draws between world and policy.
        rng = np.random.default_rng((seed, mandate_index))

        failure_class = _assign_failure_class(config, rng)
        trajectory = simulate_balance(
            mandate_amount_inr=mandate.amount_inr,
            timing_type=mandate.income_timing_type,
            horizon_days=HORIZON_DAYS,
            config=config,
            rng=rng,
        )

        # The one deliberate leak of ground truth in the entire project. `observe_trajectory` is not
        # part of the Policy contract -- only OraclePolicy implements it, so every other policy's
        # ignorance of the true balance curve stays structural, not merely a matter of not calling
        # this. The harness stays policy-agnostic: it doesn't know or care which policy this is, it
        # just offers the hook and moves on if nothing is listening.
        if hasattr(policy, "observe_trajectory"):
            policy.observe_trajectory(trajectory)

        first_failure_day = _first_consistent_failure_day(
            failure_class, mandate, trajectory, rng
        )
        current_time = mandate.created_at + timedelta(
            days=first_failure_day, hours=_first_failure_hour(failure_class, rng)
        )

        # A16: how many consecutive failures this customer tolerates before revoking the mandate
        # themselves. Drawn once per customer and held fixed -- a customer's patience is a property
        # of the customer, not something resampled at each attempt.
        revocation_threshold = sample_from_range(
            rng,
            config["failure_classes"]["mandate_revoked"][
                "revocation_trigger_consecutive_failures"
            ]["range"],
        )
        revoked_mid_sequence = False
        attempt_number = 1
        consecutive_failures = 1
        recovered = False
        days_to_recovery: float | None = None
        notification_sent_at: datetime | None = None

        while attempt_number <= max_attempts:
            state = PolicyState(
                # Redacted view: policies never receive income_timing_type. See MandateView.
                mandate=MandateView.from_mandate(mandate),
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
                # Without this the category defaulted to "general" and A6's higher ceiling could
                # never apply to anything -- see rbi_category_for and build log entry 26.
                amount_category=rbi_category_for(mandate.amount_type.value),
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
                # A26-adjacent honesty point: escalations can recover money (the customer
                # re-authenticates, re-mandates, or pays manually). The response rate (A35) is
                # applied identically to every policy, so it cannot manufacture lift by itself --
                # `NO_ACTION_POSSIBLE` (a revoked mandate) is excluded because there is genuinely
                # nothing for the customer to act on. A policy that fired a legally-refusable retry
                # instead of escalating simply has no escalation to respond to.
                if (
                    not blocked
                    and decision.escalation_action is not None
                    and decision.escalation_action != EscalationAction.NO_ACTION_POSSIBLE
                ):
                    esc = config["escalation"]
                    response_rate = rng.uniform(*esc["response_rate"]["range"])
                    if rng.uniform() < response_rate:
                        recovered = True
                        lag = float(rng.uniform(*esc["response_lag_days"]["range"]))
                        days_to_recovery = (
                            (current_time - mandate.created_at).days - first_failure_day + lag
                        )
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

            # A16: the customer's own patience runs out. A mandate that was recoverable becomes
            # permanently unrecoverable because the customer revoked it after repeated failed
            # debits -- consistent with the ~20M monthly UPI Autopay revocations attributed to
            # low balances (A9).
            #
            # This is the real cost of spending attempts badly, and it was missing entirely: before
            # this, `mandate_revoked` only ever appeared as a starting condition that both policies
            # immediately stopped on, so the revocation threshold was never read and the
            # early_revocation sensitivity scenario was silently a no-op.
            if consecutive_failures >= revocation_threshold:
                revoked_mid_sequence = True
                log.append(
                    DecisionRecord(
                        decision_id=f"{policy.name}_{mandate.mandate_id}_revoked",
                        mandate_id=mandate.mandate_id,
                        policy_name=policy.name,
                        decision_type=DecisionType.STOPPED_UNRECOVERABLE,
                        rule_id="SIM-REVOKED",
                        rule_description=(
                            f"Customer revoked the mandate after {consecutive_failures} consecutive "
                            "failed debits; no further recovery is possible"
                        ),
                        failure_class=FailureClass.MANDATE_REVOKED.value,
                        attempt_number=attempt_number,
                        decided_at=current_time,
                        source=Source.SIMULATION,
                        escalation_action=EscalationAction.NO_ACTION_POSSIBLE,
                        compliance_checks=[],
                        amount_inr=mandate.amount_inr,
                    )
                )
                break

        mandate_outcomes.append(
            MandateOutcome(
                mandate_id=mandate.mandate_id,
                amount_inr=mandate.amount_inr,
                recovered=recovered,
                is_recoverable_class=failure_class not in UNRECOVERABLE_CLASSES,
                attempts_made=attempt_number - 1 if recovered else attempt_number,
                days_to_recovery=float(days_to_recovery) if days_to_recovery is not None else None,
                revoked_mid_sequence=revoked_mid_sequence,
            )
        )

    return RunResult(
        policy_name=policy.name,
        mandate_outcomes=mandate_outcomes,
        attempt_outcomes=attempt_outcomes,
        decision_log=log,
    )
