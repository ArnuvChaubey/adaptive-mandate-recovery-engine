"""Formal metric definitions.

**These are defined before any evaluation has been run.** Defining "wasted attempt" after seeing
which policy looks better is exactly the circularity this project claims to avoid, so the definitions
land in version control first and the epsilon that drives them (A23) is frozen in sim_params.yaml.

Both recovery-rate denominators are reported, always, side by side. Reporting only the flattering one
is the easiest way to manufacture a headline number, so the harness makes it structurally awkward:
one function returns both.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AttemptOutcome:
    """One charge attempt, after the fact, with ground truth attached."""
    mandate_id: str
    amount_inr: float
    succeeded: bool
    true_success_probability: float
    is_recoverable_class: bool


@dataclass(frozen=True)
class MandateOutcome:
    """The end state of one mandate after a policy has run its course."""
    mandate_id: str
    amount_inr: float
    recovered: bool
    is_recoverable_class: bool
    attempts_made: int
    days_to_recovery: float | None
    # Customer-initiated revocation mid-sequence (A16), distinct from the mandate STARTING already
    # revoked. This is the mechanism entry 16 in the build log measures: a policy that spends
    # attempts badly loses the mandate permanently, not just the current attempt. Added for the
    # Pareto frontier -- without it, the cost of wasting attempts was visible in the build log but
    # not in a metric anyone could plot.
    revoked_mid_sequence: bool = False


@dataclass(frozen=True)
class MetricsReport:
    policy_name: str
    n_mandates: int

    recovery_rate_recoverable_only: float
    recovery_rate_all: float

    total_value_inr: float
    recovered_value_inr: float

    total_attempts: int
    wasted_attempts: int
    wasted_attempt_rate: float

    median_days_to_recovery: float | None
    iqr_days_to_recovery: tuple[float, float] | None

    # A16. The real cost of a policy that spends attempts badly: the customer revokes before the
    # policy's own strategy gets to play out. Denominator is all mandates, not just recoverable
    # ones -- a mandate that started unrecoverable was never at risk of THIS kind of revocation.
    revocation_rate: float = 0.0


def is_wasted_attempt(outcome: AttemptOutcome, epsilon: float) -> bool:
    """A23. An attempt is wasted if it was fired at a moment when simulator ground truth says it had
    essentially no chance of succeeding -- true success probability at or below epsilon.

    Epsilon is frozen in config (`metrics.wasted_attempt_epsilon`) before any run. It is never
    adjusted after seeing results; doing so would let the metric be redefined to flatter whichever
    policy looked worse.

    Note this is deliberately a ground-truth measure, not an outcome measure. An attempt that failed
    but had a genuine chance of succeeding was a reasonable bet, not a waste. Scoring "wasted" by
    outcome would punish good decisions that got unlucky.
    """
    return outcome.true_success_probability <= epsilon


def compute_metrics(
    policy_name: str,
    mandate_outcomes: list[MandateOutcome],
    attempt_outcomes: list[AttemptOutcome],
    config: dict,
) -> MetricsReport:
    epsilon = config["metrics"]["wasted_attempt_epsilon"]["value"]

    recoverable = [m for m in mandate_outcomes if m.is_recoverable_class]
    recovered = [m for m in mandate_outcomes if m.recovered]

    # A24: both denominators, always. The recoverable-only figure excludes mandates no policy could
    # ever have saved (expired/revoked); the all-mandates figure includes them. Neither is "the"
    # number -- reporting one without the other is how a lift claim gets quietly inflated.
    recovery_rate_recoverable = len(recovered) / len(recoverable) if recoverable else 0.0
    recovery_rate_all = len(recovered) / len(mandate_outcomes) if mandate_outcomes else 0.0

    wasted = sum(1 for a in attempt_outcomes if is_wasted_attempt(a, epsilon))

    recovery_times = [m.days_to_recovery for m in recovered if m.days_to_recovery is not None]
    if recovery_times:
        median_days = float(np.median(recovery_times))
        iqr = (float(np.percentile(recovery_times, 25)), float(np.percentile(recovery_times, 75)))
    else:
        median_days, iqr = None, None

    revoked = sum(1 for m in mandate_outcomes if m.revoked_mid_sequence)

    return MetricsReport(
        policy_name=policy_name,
        n_mandates=len(mandate_outcomes),
        recovery_rate_recoverable_only=recovery_rate_recoverable,
        recovery_rate_all=recovery_rate_all,
        total_value_inr=sum(m.amount_inr for m in mandate_outcomes),
        recovered_value_inr=sum(m.amount_inr for m in recovered),
        total_attempts=len(attempt_outcomes),
        wasted_attempts=wasted,
        wasted_attempt_rate=wasted / len(attempt_outcomes) if attempt_outcomes else 0.0,
        median_days_to_recovery=median_days,
        iqr_days_to_recovery=iqr,
        revocation_rate=revoked / len(mandate_outcomes) if mandate_outcomes else 0.0,
    )


def recovery_lift(baseline: MetricsReport, candidate: MetricsReport) -> dict[str, float]:
    """Relative lift of a candidate policy over baseline, per metric.

    Never reported as a single headline decimal -- Milestone 4 computes this per scenario across the
    swept assumption ranges and reports the distribution, including scenarios where lift is negative.
    A harness that only ever flatters its own reference policy is not a harness.
    """
    def rel(new: float, old: float) -> float:
        if old == 0:
            return 0.0 if new == 0 else float("inf")
        return (new - old) / old

    return {
        "recovery_rate_recoverable_only": rel(
            candidate.recovery_rate_recoverable_only, baseline.recovery_rate_recoverable_only
        ),
        "recovery_rate_all": rel(candidate.recovery_rate_all, baseline.recovery_rate_all),
        "recovered_value_inr": rel(candidate.recovered_value_inr, baseline.recovered_value_inr),
        # Negative is better here: fewer wasted attempts.
        "wasted_attempt_rate": rel(candidate.wasted_attempt_rate, baseline.wasted_attempt_rate),
        # Negative is better here too: fewer customers driven to revoke.
        "revocation_rate": rel(candidate.revocation_rate, baseline.revocation_rate),
    }
