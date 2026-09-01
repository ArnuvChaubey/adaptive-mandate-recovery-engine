"""Pins that the benchmark measures the same decision path production uses.

A benchmark that drifts from the code it claims to measure reports a number about nothing. Since
`eval/benchmark.py` necessarily reconstructs the per-decision path outside the harness loop, the risk
is that the two quietly diverge -- someone adds an invariant, or changes the veto, and the throughput
figure keeps being quoted for a path that no longer exists.

Both now call the same `apply_compliance_veto` and the same `evaluate_all`, so the remaining risk is
the glue. These tests pin the glue: for the same input, the benchmark must produce the same recorded
decision type the harness would.
"""

from datetime import datetime, timedelta

import pytest

from audit.decision_log_schema.records import DecisionType
from compliance.invariants.rules import (
    ProposedDecision,
    apply_compliance_veto,
    evaluate_all,
    rbi_category_for,
)
from eval.benchmark import build_states, decide_and_check
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.policy_interface.base import MandateView, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass


def _harness_equivalent(policy, state: PolicyState, config: dict) -> DecisionType:
    """The decision path exactly as eval/harness.py performs it, minus the audit write."""
    decision = policy.decide(state, config)
    proposed = ProposedDecision(
        mandate_id=state.mandate.mandate_id,
        amount_inr=state.mandate.amount_inr,
        scheduled_retry_at=decision.scheduled_retry_at,
        notification_sent_at=decision.notification_to_send_at,
        amount_category=rbi_category_for(state.mandate.amount_type.value),
        is_new_notification=decision.notification_to_send_at is not None,
    )
    checks = evaluate_all(proposed, config)
    return apply_compliance_veto(decision.decision_type, checks)


def test_benchmark_path_matches_harness_path_for_every_state():
    """The load-bearing test: if these ever disagree, the throughput number is measuring fiction."""
    config = load_config()
    policy = AdaptivePolicy()
    for state in build_states(300):
        assert decide_and_check(policy, state, config) == _harness_equivalent(policy, state, config)


def test_benchmark_states_exercise_every_failure_class():
    """A benchmark that only ever hits the cheapest branch overstates throughput."""
    states = build_states(60)
    seen = {s.failure_class for s in states}
    assert seen == set(FailureClass), f"missing failure classes: {set(FailureClass) - seen}"


def test_benchmark_states_straddle_the_otp_ceiling():
    """Must exercise the escalation branch too, not just retries."""
    config = load_config()
    ceiling = config["compliance_floors"]["otp_free_ceiling_inr"]["value"]
    amounts = {s.mandate.amount_inr for s in build_states(60)}
    assert any(a <= ceiling for a in amounts), "no below-ceiling amounts"
    assert any(a > ceiling for a in amounts), "no above-ceiling amounts -- escalation never measured"


def test_benchmark_actually_produces_a_mix_of_outcomes():
    """If every state produced the same decision type, the measurement would be degenerate."""
    config = load_config()
    policy = AdaptivePolicy()
    outcomes = {decide_and_check(policy, s, config) for s in build_states(120)}
    assert len(outcomes) >= 3, f"benchmark exercises too few decision types: {outcomes}"
