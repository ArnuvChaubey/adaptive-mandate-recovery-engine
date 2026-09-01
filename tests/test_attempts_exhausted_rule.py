"""Covers ADAPT-003 / BASE-002, the attempt-cap stopping rule — which had no test at all, and never
fires in practice.

Found while verifying the project against Track 03's "stopping rules" clause: across all 30 seeds and
6,000 mandates, `stopped_attempts_exhausted` appears **zero times**. Every other rule fires hundreds
to thousands of times.

That is not the entry-26 bug repeating. The rule is genuinely reachable — these tests call it directly
and it fires correctly. The reason it never fires in a real batch is an emergent interaction between
two separately-sourced parameters:

  - A20 (FACT, cited): a subscription halts after 4 attempts.
  - A16 (ASSUMPTION, swept [2,4]): a customer revokes after 2-4 *consecutive* failed debits.

A16's threshold is always <= A20's cap, so customer revocation converts the mandate to
`mandate_revoked` — caught by ADAPT-001, which sits above ADAPT-003 in the ladder — before the attempt
budget can ever be exhausted. **The documented stopping rule is real and enforced, but under this
parameterisation it is never the binding constraint; customer patience is.** That is a finding worth
stating, not a defect worth hiding, and it is exactly the kind of thing that stays invisible without a
test that asks whether a rule can fire at all.
"""

from datetime import datetime

import pytest

from audit.decision_log_schema.records import DecisionType, EscalationAction
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.baseline_policy.policy import BaselinePolicy
from policies.policy_interface.base import MandateView, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass

RECOVERABLE = FailureClass.INSUFFICIENT_FUNDS


def _state(attempt_number: int, failure_class=RECOVERABLE, amount=5_000.0) -> PolicyState:
    return PolicyState(
        mandate=MandateView(
            mandate_id="t1",
            amount_inr=amount,
            amount_type=AmountType.OTT_SUBSCRIPTION,
            created_at=datetime(2026, 7, 1),
            validity_days=365,
        ),
        failure_class=failure_class,
        attempt_number=attempt_number,
        failed_at=datetime(2026, 8, 1, 9, 0),
        consecutive_failures=attempt_number,
    )


@pytest.mark.parametrize("policy_cls", [AdaptivePolicy, BaselinePolicy])
def test_attempt_cap_stops_at_the_configured_maximum(policy_cls):
    """The rule fires at the cap, for both policy families -- proving it is reachable, not dead."""
    config = load_config()
    cap = config["retry_policy_shared"]["max_attempts"]["value"]
    decision = policy_cls().decide(_state(attempt_number=cap), config)
    assert decision.decision_type == DecisionType.STOPPED_ATTEMPTS_EXHAUSTED


@pytest.mark.parametrize("policy_cls", [AdaptivePolicy, BaselinePolicy])
def test_below_the_cap_still_retries(policy_cls):
    """The boundary must not be off by one -- one attempt below the cap must still retry."""
    config = load_config()
    cap = config["retry_policy_shared"]["max_attempts"]["value"]
    decision = policy_cls().decide(_state(attempt_number=cap - 1), config)
    assert decision.decision_type == DecisionType.RETRY_SCHEDULED


def test_the_stop_names_a_next_action_rather_than_giving_up():
    """'Compliant escalation' means a stop must name what happens instead -- the Decision type
    enforces this, but pin the specific action so a future edit can't silently downgrade it to
    NO_ACTION_POSSIBLE, which would mean abandoning a recoverable mandate."""
    config = load_config()
    decision = AdaptivePolicy().decide(_state(attempt_number=4), config)
    assert decision.escalation_action == EscalationAction.NOTIFY_CUSTOMER_MANUAL_PAYMENT
    assert decision.escalation_action != EscalationAction.NO_ACTION_POSSIBLE


def test_cap_tracks_the_config_rather_than_being_hardcoded():
    """If A20's documented halt condition ever changes, the stopping rule must move with it."""
    config = load_config()
    real_cap = config["retry_policy_shared"]["max_attempts"]["value"]
    raised = {
        **config,
        "retry_policy_shared": {
            **config["retry_policy_shared"],
            "max_attempts": {**config["retry_policy_shared"]["max_attempts"], "value": real_cap + 2},
        },
    }
    # At the OLD cap, a raised config must now permit a retry rather than stopping.
    decision = AdaptivePolicy().decide(_state(attempt_number=real_cap), raised)
    assert decision.decision_type == DecisionType.RETRY_SCHEDULED


def test_unrecoverable_takes_priority_over_the_attempt_cap():
    """Documents the ladder order that makes ADAPT-003 unreachable in practice: a revoked mandate at
    the cap stops as unrecoverable (ADAPT-001), not as attempts-exhausted, because ADAPT-001 is
    checked first. This is why customer revocation (A16) always bites before the attempt cap (A20)
    in a real batch -- the behaviour is correct, and this pins the precedence so a reordering of the
    rule ladder can't change it silently."""
    config = load_config()
    decision = AdaptivePolicy().decide(
        _state(attempt_number=4, failure_class=FailureClass.MANDATE_REVOKED), config
    )
    assert decision.decision_type == DecisionType.STOPPED_UNRECOVERABLE
    assert decision.rule_id == "ADAPT-001"
