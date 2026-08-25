"""The six failure-class generators.

Each returns the ground-truth probability that a charge attempt succeeds at a given moment, given
the failure class in play. These are pure functions of (context, config, rng) -- no global random
state, so every run is reproducible from its seed.

Nothing here knows anything about retry policy. The simulator answers "what does the world look
like"; policies answer "what should we do about it". Keeping that boundary clean is what makes the
Day 5-6 baseline-vs-adaptive comparison non-circular.
"""

from dataclasses import dataclass
from datetime import datetime, time

import numpy as np

from simulator.config_loader import sample_from_range
from simulator.mandate import FailureClass, Mandate


@dataclass(frozen=True)
class AttemptContext:
    """Everything the world knows at the moment of a charge attempt."""
    mandate: Mandate
    attempt_time: datetime
    day_index: int              # days since mandate creation
    balance_inr: float          # current simulated account balance
    notification_delivered: bool
    consecutive_failures: int


def _parse_window(window: list[str]) -> tuple[time, time]:
    start_h, start_m = (int(x) for x in window[0].split(":"))
    end_h, end_m = (int(x) for x in window[1].split(":"))
    return time(start_h, start_m), time(end_h, end_m)


def insufficient_funds_success_probability(
    ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    """A10: no public source maps aggregate revocation volume to a per-attempt probability, so this
    is derived from the simulated balance rather than a looked-up rate.

    Day 3 placeholder: a step function on whether the balance covers the amount. Day 4 replaces the
    balance input itself with the stochastic income/decay process (A14/A15); this function's shape
    stays, but the balance driving it becomes far more realistic.
    """
    if ctx.balance_inr >= ctx.mandate.amount_inr:
        return 1.0
    shortfall_ratio = ctx.balance_inr / max(ctx.mandate.amount_inr, 1e-9)
    # Partial-balance attempts still fail (banks don't part-debit a mandate), but a near-sufficient
    # balance signals the customer is close to being able to pay -- relevant to retry timing.
    return float(np.clip(shortfall_ratio * 0.1, 0.0, 0.1))


def notification_undelivered_success_probability(
    ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    """A4/A5: RBI requires a pre-debit notice at least 24h before an automated debit. If the notice
    wasn't delivered, the debit is blocked -- a hard compliance floor, not a timing preference.

    Note this is the *simulator* enforcing what the world does. The matching constraint on the
    policy side lives in compliance/invariants/ so a policy cannot silently bypass it.
    """
    if not ctx.notification_delivered:
        return 0.0
    return 1.0


def npci_congestion_success_probability(
    ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    """A7 (window timing, evidenced) + A8 (degradation magnitude, no public source at all).

    NPCI's 2026 Traffic Management framework deprioritizes automated mandates during peak hours.
    The window is documented; how much success actually degrades inside it is not, anywhere -- so
    the magnitude is swept, never asserted as a point estimate.
    """
    cfg = config["failure_classes"]["npci_congestion"]
    start, end = _parse_window(cfg["bad_window_local_time"])
    attempt_t = ctx.attempt_time.time()

    if start <= attempt_t < end:
        degradation = sample_from_range(rng, cfg["success_probability_degradation"]["range"])
        return float(np.clip(1.0 - degradation, 0.0, 1.0))
    return 1.0


def bank_technical_decline_success_probability(
    ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    """A31: least-evidenced class in the taxonomy -- no public source for base rate or recovery
    behavior. Modeled as transient by definition: a decline that isn't tied to funds, notification,
    or congestion is assumed to clear on its own, so a later attempt is unaffected by an earlier one.
    """
    base_rate = sample_from_range(rng, config["failure_classes"]["bank_technical_decline"]["base_rate"]["range"])
    return float(np.clip(1.0 - base_rate, 0.0, 1.0))


def mandate_expired_success_probability(
    ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    """A19: definitional. Past expiry there is no authorization to debit against -- no retry timing
    can recover this, which is precisely why the policy's correct move is to stop and escalate."""
    if ctx.day_index >= ctx.mandate.validity_days:
        return 0.0
    return 1.0


def mandate_revoked_success_probability(
    ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    """A16/A19: a revoked mandate is unrecoverable. A16 governs when a customer gives up and revokes
    after repeated failures -- arguably the thing an adaptive policy exists to avoid triggering."""
    cfg = config["failure_classes"]["mandate_revoked"]
    threshold = sample_from_range(rng, cfg["revocation_trigger_consecutive_failures"]["range"])
    if ctx.consecutive_failures >= threshold:
        return 0.0
    return 1.0


SUCCESS_PROBABILITY_FUNCTIONS = {
    FailureClass.INSUFFICIENT_FUNDS: insufficient_funds_success_probability,
    FailureClass.NOTIFICATION_UNDELIVERED: notification_undelivered_success_probability,
    FailureClass.NPCI_CONGESTION: npci_congestion_success_probability,
    FailureClass.BANK_TECHNICAL_DECLINE: bank_technical_decline_success_probability,
    FailureClass.MANDATE_EXPIRED: mandate_expired_success_probability,
    FailureClass.MANDATE_REVOKED: mandate_revoked_success_probability,
}


def success_probability(
    failure_class: FailureClass, ctx: AttemptContext, config: dict, rng: np.random.Generator
) -> float:
    return SUCCESS_PROBABILITY_FUNCTIONS[failure_class](ctx, config, rng)
