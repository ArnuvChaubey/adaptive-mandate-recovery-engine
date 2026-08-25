"""The account-balance stochastic process.

**This is the largest assumption cluster in the project (A14, A15), and both are LOW confidence.**
No public dataset describes Indian retail account-balance trajectories at any granularity, so the
shape here -- balance rises at income events, decays between them, with noise -- is an inference from
general financial behaviour, not a fitted or cited curve.

It is isolated in its own module deliberately: it should be the easiest thing in the repo for a
skeptical reviewer to find, interrogate, and replace. Every parameter is read from a swept range in
the frozen config; none is a tuned point estimate.

Deliberate non-goal: this is NOT calibrated to make `insufficient_funds` produce a "realistic-looking"
failure rate. Tuning ground truth until the output matches intuition would be fitting the world to
the answer we expect. Whatever failure rate falls out of the swept ranges is the failure rate.
"""

from dataclasses import dataclass

import numpy as np

from simulator.config_loader import sample_from_range
from simulator.mandate import IncomeTimingType
from simulator.population.income_events import income_event_days


@dataclass(frozen=True)
class BalanceTrajectory:
    """Daily closing balance over the simulation horizon."""
    daily_balance_inr: np.ndarray
    income_days: frozenset[int]

    def balance_on(self, day_index: int) -> float:
        idx = min(max(day_index, 0), len(self.daily_balance_inr) - 1)
        return float(self.daily_balance_inr[idx])


def simulate_balance(
    mandate_amount_inr: float,
    timing_type: IncomeTimingType,
    horizon_days: int,
    config: dict,
    rng: np.random.Generator,
) -> BalanceTrajectory:
    """Simulates one customer's balance over the horizon.

    Income is scaled relative to the mandate amount rather than drawn from an absolute income
    distribution -- we have no source for Indian income distributions either, and what actually
    matters for this experiment is the *ratio* of available balance to the amount being debited.
    Scaling sidesteps inventing an income distribution we'd have to defend separately.
    """
    cfg = config["balance_evolution"]
    decay_rate = sample_from_range(rng, cfg["decay_rate_range"])
    volatility = sample_from_range(rng, cfg["volatility_range"])

    income_days = income_event_days(timing_type, horizon_days, rng)

    # Income as a multiple of the mandate amount. Wide and unsourced (part of A15's cluster): some
    # customers comfortably cover the mandate, others are near the edge, which is precisely the
    # population where retry timing matters at all.
    income_multiple = float(rng.uniform(1.5, 8.0))
    income_amount = mandate_amount_inr * income_multiple

    balances = np.zeros(horizon_days, dtype=float)
    balance = income_amount * float(rng.uniform(0.1, 0.5))  # start mid-cycle, not flush

    for day in range(horizon_days):
        if day in income_days:
            balance += income_amount
        spend = balance * decay_rate * float(rng.normal(1.0, volatility))
        balance = max(0.0, balance - max(0.0, spend))
        balances[day] = balance

    return BalanceTrajectory(daily_balance_inr=balances, income_days=frozenset(income_days))
