"""Oracle policy -- a deliberately unfair ceiling, never a deployable candidate.

Every other policy in this project answers "what should we do, given what a real system could
know." This one answers a different question: "how much better could ANY policy possibly do, if it
knew things no real system ever could?" That's a standard technique across several fields -- perfect-
information optimum in operations research, oracle forecast in forecasting, expert policy in RL -- and
nobody expects the answer to be deployable. Its only job is to establish the ceiling everything else
is measured against.

**Precisely scoped foreknowledge, not omniscience.** The oracle sees exactly one thing a real system
cannot: the customer's true balance trajectory over the full horizon. It does NOT see the customer's
private revocation threshold, does NOT see which random draw notification delivery or a technical
decline will land on, and does NOT get extra attempts or an exemption from the OTP ceiling. Extending
its knowledge indefinitely would make "oracle" meaningless -- this is bounded, specific foreknowledge
about the one thing that actually matters, not a policy that gets to win by cheating on the rules
everyone else has to follow.

**Why it only overrides one thing.** Tracing through every success-probability function in
simulator/failure_events/generators.py: day-of-attempt timing changes the ground-truth probability
for exactly two failure classes -- `insufficient_funds` (via the balance curve) and `npci_congestion`
(via the hour-of-day window). Every other class's probability is either day-independent
(notification delivery, technical decline) or a hard stop regardless of timing (expired, revoked).
And congestion is already fully solved by AdaptivePolicy's existing avoidance rule -- once the retry
hour is fixed outside the bad window, every day is equally good, so foreknowledge adds nothing there.

That leaves exactly one place the oracle can possibly beat adaptive: `insufficient_funds`, where
adaptive guesses a population-level payday (A12/A13) and the oracle instead reads the real curve. So
the oracle IS the adaptive policy, with that one guess replaced by the true answer. Everywhere else,
it inherits adaptive's behaviour unchanged -- including the 4-attempt cap, the OTP-ceiling escalation,
and the unrecoverable-class stop. If adaptive is already at the ceiling for four of six failure
classes, the oracle should show that by matching it there, not by mysteriously doing better everywhere
for reasons nobody can point to.

**Greedy, not globally optimal.** At each decision point the oracle picks the single best next day
within the same wait budget adaptive uses (`MAX_WAIT_DAYS`). It does not run a joint search over all
four attempts to find the globally optimal sequence -- that's a harder dynamic-programming problem
that would buy little additional insight for a lot more code, and greedy-per-step is already strictly
more informed than any deployable policy. Call it a strong upper bound, not claim it's exhaustively
optimal.

**When there's no good day.** If the balance never covers the amount anywhere in the window, the
oracle picks the day the shortfall is smallest -- the least-bad option, not a guarantee. This is
honest: even perfect information about a genuinely broke account can't manufacture money. Oracle
recovery rate should be high, not 100%.
"""

from datetime import datetime, timedelta

import numpy as np

from policies.adaptive_policy.policy import (
    MAX_WAIT_DAYS,
    SETTLEMENT_BUFFER_DAYS,
    AdaptivePolicy,
)
from policies.policy_interface.base import PolicyState
from simulator.failure_events.generators import AttemptContext, insufficient_funds_success_probability
from simulator.mandate import FailureClass

RULE_ORACLE_PERFECT_TIMING = "ORACLE-004"

# Passed to the ground-truth probability function where the signature requires an rng, but the
# insufficient-funds function never actually draws from it (verified in generators.py -- it's a pure
# function of the balance ratio). Using a fixed, throwaway generator makes that non-use explicit and
# guarantees the oracle's search never perturbs the harness's own shared random stream.
_UNUSED_RNG = np.random.default_rng(0)


class OraclePolicy(AdaptivePolicy):
    """Never register this as a deployable candidate. It exists to be compared against, not to win."""

    name = "oracle"

    def __init__(self) -> None:
        super().__init__()
        # Injected by the harness, once per mandate, via the `observe_trajectory` hook below -- the
        # one deliberate, visible violation of the MandateView boundary in the entire project. No
        # other policy implements this hook, and the harness only calls it if a policy has it.
        self.current_trajectory = None

    def observe_trajectory(self, trajectory) -> None:
        """The escape hatch. Only the oracle implements this; only the harness calls it, and only
        for the oracle. Every other policy's ignorance of the trajectory remains structural."""
        self.current_trajectory = trajectory

    def _schedule(
        self, state: PolicyState, config: dict, notification_at: datetime
    ) -> tuple[str, str, datetime]:
        if state.failure_class != FailureClass.INSUFFICIENT_FUNDS or self.current_trajectory is None:
            # Every other failure class: identical to AdaptivePolicy. Foreknowledge buys nothing
            # here, so the oracle doesn't pretend otherwise.
            return super()._schedule(state, config, notification_at)

        min_hours = config["failure_classes"]["notification_undelivered"][
            "min_hours_between_notification_and_debit"
        ]["value"]
        earliest = notification_at + timedelta(hours=min_hours)
        latest = state.failed_at + timedelta(days=MAX_WAIT_DAYS)

        best_day, best_prob = None, -1.0
        day = earliest
        while day <= latest:
            day_index = (day - state.mandate.created_at).days
            if 0 <= day_index < len(self.current_trajectory.daily_balance_inr):
                # state.mandate is a MandateView, which carries amount_inr -- so this calls the
                # SAME ground-truth function the harness later uses to decide whether the executed
                # attempt actually succeeds. The search and the real outcome are provably evaluating
                # identical logic, not two implementations that are merely intended to agree.
                ctx = AttemptContext(
                    mandate=state.mandate,
                    attempt_time=day,
                    day_index=day_index,
                    balance_inr=self.current_trajectory.balance_on(day_index),
                    notification_delivered=True,
                    consecutive_failures=state.consecutive_failures,
                )
                prob = insufficient_funds_success_probability(ctx, config, _UNUSED_RNG)
                if prob > best_prob:
                    best_day, best_prob = day, prob
                if prob >= 1.0:
                    break  # fully funded -- earliest such day is strictly best, stop searching
            day += timedelta(days=1)

        retry_at = best_day if best_day is not None else earliest + timedelta(days=SETTLEMENT_BUFFER_DAYS)

        return (
            RULE_ORACLE_PERFECT_TIMING,
            (
                "Perfect information about the true balance trajectory: retry on "
                f"{retry_at.date()}, the day within the search window with the highest true "
                f"success probability ({best_prob:.2f}) -- not a guessed population-level payday"
            ),
            retry_at,
        )
