"""Oracle policy tests.

The interesting claims to pin down: the oracle respects every constraint a deployable policy does
(it's a ceiling on TIMING, not an exemption from the rules), it never does worse than adaptive, and
its advantage is concentrated specifically in insufficient_funds -- if it started winning everywhere,
that would mean the "day doesn't matter for the other five classes" analysis in the module docstring
was wrong, and the whole scoping argument would need revisiting.
"""

from datetime import datetime, timedelta

import pytest

from audit.decision_log_schema.records import DecisionType, EscalationAction
from eval.harness import run_policy_on_batch
from eval.metrics.definitions import compute_metrics
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.oracle_policy.policy import OraclePolicy
from policies.policy_interface.base import MandateView, PolicyState
from simulator.balance_evolution.process import BalanceTrajectory
from simulator.batch import generate_mandates
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass

import numpy as np

BASE_TIME = datetime(2026, 3, 1, 12, 0)


@pytest.fixture
def config():
    return load_config()


def make_state(**overrides) -> PolicyState:
    mandate = overrides.pop("mandate", None) or MandateView(
        mandate_id="m1", amount_inr=500.0, amount_type=AmountType.OTT_SUBSCRIPTION,
        created_at=BASE_TIME, validity_days=365,
    )
    defaults = dict(
        mandate=mandate, failure_class=FailureClass.INSUFFICIENT_FUNDS, attempt_number=1,
        failed_at=BASE_TIME, consecutive_failures=1, notification_sent_at=None,
    )
    defaults.update(overrides)
    return PolicyState(**defaults)


def make_trajectory(daily_balances: list[float]) -> BalanceTrajectory:
    return BalanceTrajectory(daily_balance_inr=np.array(daily_balances), income_days=frozenset())


# ---------------------------------------------------------------------------------------------
# Without observe_trajectory, the oracle must not silently misbehave
# ---------------------------------------------------------------------------------------------

def test_oracle_without_trajectory_falls_back_to_adaptive_behaviour(config):
    """If nothing ever calls observe_trajectory (e.g. a future caller that isn't the harness), the
    oracle must not crash or silently make something up -- it degrades to plain adaptive behaviour."""
    oracle = OraclePolicy()
    adaptive = AdaptivePolicy()
    state = make_state()
    o = oracle.decide(state, config)
    a = adaptive.decide(state, config)
    assert o.rule_id == a.rule_id
    assert o.scheduled_retry_at == a.scheduled_retry_at


# ---------------------------------------------------------------------------------------------
# The search itself
# ---------------------------------------------------------------------------------------------

def test_oracle_picks_the_earliest_fully_funded_day(config):
    """Balance covers the amount from day 10 onward. The oracle should pick day 10, not linger."""
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory([0.0] * 10 + [1000.0] * 80))
    state = make_state(mandate=MandateView(
        mandate_id="m1", amount_inr=500.0, amount_type=AmountType.OTT_SUBSCRIPTION,
        created_at=BASE_TIME, validity_days=365,
    ))
    decision = oracle.decide(state, config)
    assert decision.decision_type == DecisionType.RETRY_SCHEDULED
    picked_day = (decision.scheduled_retry_at - BASE_TIME).days
    assert picked_day <= 11  # allows for the 24h notification floor pushing it a day later


def test_oracle_prefers_a_fully_funded_day_over_an_earlier_partial_one(config):
    """Day 2 is partially funded (would still fail); day 5 is fully funded. The oracle must not
    settle for the earlier near-miss when a certain win is reachable within the wait budget."""
    balances = [0.0] * 90
    balances[2] = 200.0   # 40% of a 500 mandate -- still fails
    balances[5] = 600.0   # fully funded
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory(balances))
    state = make_state()
    decision = oracle.decide(state, config)
    picked_day = (decision.scheduled_retry_at - BASE_TIME).days
    assert picked_day in (5, 6)  # day 5, or pushed to 6 by the notification floor


def test_oracle_falls_back_to_least_bad_day_when_never_fully_funded(config):
    """Chronically short account: even perfect information can't manufacture money. The oracle picks
    the closest-to-sufficient day rather than claiming certainty it doesn't have."""
    balances = [50.0] * 90
    balances[20] = 400.0  # best available, still short of 500
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory(balances))
    state = make_state()
    decision = oracle.decide(state, config)
    assert decision.decision_type == DecisionType.RETRY_SCHEDULED
    picked_day = (decision.scheduled_retry_at - BASE_TIME).days
    assert 19 <= picked_day <= 21


# ---------------------------------------------------------------------------------------------
# Everywhere else, the oracle is exactly the adaptive policy -- no silent extra advantage
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("failure_class", [
    FailureClass.NPCI_CONGESTION,
    FailureClass.NOTIFICATION_UNDELIVERED,
    FailureClass.BANK_TECHNICAL_DECLINE,
])
def test_oracle_matches_adaptive_on_classes_where_timing_doesnt_matter(config, failure_class):
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory([1000.0] * 90))  # present, but irrelevant here
    adaptive = AdaptivePolicy()
    state = make_state(failure_class=failure_class)

    o = oracle.decide(state, config)
    a = adaptive.decide(state, config)
    assert o.rule_id == a.rule_id
    assert o.scheduled_retry_at == a.scheduled_retry_at


def test_oracle_respects_the_same_attempt_cap(config):
    max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory([1000.0] * 90))
    decision = oracle.decide(make_state(attempt_number=max_attempts), config)
    assert decision.decision_type == DecisionType.STOPPED_ATTEMPTS_EXHAUSTED


def test_oracle_escalates_above_the_otp_ceiling_like_everyone_else(config):
    """Perfect information about a customer's balance does not exempt anyone from a legal
    requirement -- the oracle is a ceiling on timing intelligence, not on compliance."""
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory([1_000_000.0] * 90))  # plenty of money, irrelevant
    big = MandateView(
        mandate_id="m2", amount_inr=30_000.0, amount_type=AmountType.EMI,
        created_at=BASE_TIME, validity_days=365,
    )
    decision = oracle.decide(make_state(mandate=big), config)
    assert decision.decision_type == DecisionType.ESCALATED
    assert decision.escalation_action == EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION


def test_oracle_stops_immediately_on_unrecoverable_classes(config):
    oracle = OraclePolicy()
    oracle.observe_trajectory(make_trajectory([1000.0] * 90))
    decision = oracle.decide(make_state(failure_class=FailureClass.MANDATE_REVOKED), config)
    assert decision.decision_type == DecisionType.STOPPED_UNRECOVERABLE


# ---------------------------------------------------------------------------------------------
# End-to-end: the oracle must never lose to adaptive, and its edge must be where predicted
# ---------------------------------------------------------------------------------------------

def test_oracle_never_recovers_less_value_than_adaptive_across_a_batch(config):
    mandates = generate_mandates(200, seed=1, config=config)
    adaptive_result = run_policy_on_batch(AdaptivePolicy(), mandates, config, seed=1)
    oracle_result = run_policy_on_batch(OraclePolicy(), mandates, config, seed=1)

    adaptive_metrics = compute_metrics("adaptive", adaptive_result.mandate_outcomes,
                                        adaptive_result.attempt_outcomes, config)
    oracle_metrics = compute_metrics("oracle", oracle_result.mandate_outcomes,
                                      oracle_result.attempt_outcomes, config)

    assert oracle_metrics.recovered_value_inr >= adaptive_metrics.recovered_value_inr
    assert oracle_metrics.recovery_rate_recoverable_only >= adaptive_metrics.recovery_rate_recoverable_only


def test_oracle_never_proposes_a_non_compliant_retry(config):
    """The harness's compliance veto should never actually have to block the oracle -- it respects
    the same floors by construction, inherited unchanged from AdaptivePolicy."""
    mandates = generate_mandates(200, seed=2, config=config)
    result = run_policy_on_batch(OraclePolicy(), mandates, config, seed=2)
    assert len(result.decision_log.compliance_failures()) == 0
