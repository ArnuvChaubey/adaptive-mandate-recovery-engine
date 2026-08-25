"""Adaptive policy, hedged variant.

**Why this exists.** The first adaptive policy beat baseline on recovery and money but *lost* badly
on wasted attempts (+202%, worse in 13 of 15 sensitivity scenarios). Diagnosis in
docs/build_log.md entry 11: all of the regression sits in `insufficient_funds`. Waiting ~30 days for
a population-level income event wins for customers who follow the pattern and fires into a
completely drained account for the 20-40% who do not (A13). It converts near-miss failures into
confident misses.

**The change is one rule.** Instead of spending the whole budget on a single bet:

    attempt 1  -> probe as soon as the 24h notification floor allows
    attempt 2+ -> wait for the next likely income event, as before

The first attempt is cheap in calendar terms and the account was only *just* short, so a marginal
recovery is plausible. The income-event bet is preserved for later attempts rather than being the
only thing tried.

**This is policy iteration after seeing results, and that is disclosed rather than hidden.** It is
legitimate -- the freeze protects simulator ground truth, not the policy, and tuning a policy against
fixed ground truth is the entire point of having a harness. `adaptive` is kept unchanged alongside
this so both are reported and the change is auditable.

**It is not obviously an improvement.** Spending an extra attempt raises exposure to A16: customers
revoke after 2-4 consecutive failed debits, so an early probe that fails pushes threshold-2 customers
into revocation sooner, permanently losing a mandate the unhedged policy might have recovered in one
well-timed attempt. Whether the hedge pays depends on which effect dominates -- which is a question
for the sweep, not for argument.
"""

from datetime import datetime, timedelta

from policies.adaptive_policy.policy import AdaptivePolicy
from policies.policy_interface.base import PolicyState
from simulator.mandate import FailureClass

RULE_HEDGED_PROBE = "ADAPT-H-004A"
RULE_HEDGED_AWAIT_INCOME = "ADAPT-H-004B"

# The attempt on which the policy stops probing and starts waiting for an income event.
PROBE_ATTEMPTS = 1


class AdaptiveHedgedPolicy(AdaptivePolicy):
    name = "adaptive_hedged"

    def _schedule(
        self, state: PolicyState, config: dict, notification_at: datetime
    ) -> tuple[str, str, datetime]:
        if state.failure_class != FailureClass.INSUFFICIENT_FUNDS:
            # Every other failure class is unchanged -- the regression was confined to this one.
            return super()._schedule(state, config, notification_at)

        if state.attempt_number <= PROBE_ATTEMPTS:
            min_hours = config["failure_classes"]["notification_undelivered"][
                "min_hours_between_notification_and_debit"
            ]["value"]
            return (
                RULE_HEDGED_PROBE,
                (
                    f"Insufficient funds, attempt {state.attempt_number}: probe as soon as the "
                    f"{min_hours}h notification floor allows. The account was only marginally short, "
                    "so a cheap early attempt is preferred to committing the whole budget to a "
                    "single income-event bet"
                ),
                notification_at + timedelta(hours=min_hours + 1),
            )

        rule_id, description, retry_at = super()._schedule(state, config, notification_at)
        return (
            RULE_HEDGED_AWAIT_INCOME,
            f"Early probe already spent; {description[0].lower()}{description[1:]}",
            retry_at,
        )
