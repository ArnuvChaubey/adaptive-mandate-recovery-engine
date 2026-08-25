"""Policy contract and baseline behaviour tests."""

from datetime import datetime, timedelta

import pytest

from audit.decision_log_schema.records import DecisionType, EscalationAction
from policies.baseline_policy.policy import BaselinePolicy
from policies.external_policy_stub.policy import ExternalPolicyStub
from policies.policy_interface.base import Decision, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass, IncomeTimingType, Mandate

BASE_TIME = datetime(2026, 3, 1, 12, 0)


@pytest.fixture
def config():
    return load_config()


def make_state(**overrides) -> PolicyState:
    mandate = overrides.pop("mandate", None) or Mandate(
        mandate_id="m1",
        amount_inr=500.0,
        amount_type=AmountType.OTT_SUBSCRIPTION,
        income_timing_type=IncomeTimingType.CLUSTERED_NEAR_7TH,
        created_at=BASE_TIME,
        validity_days=365,
    )
    defaults = dict(
        mandate=mandate,
        failure_class=FailureClass.INSUFFICIENT_FUNDS,
        attempt_number=1,
        failed_at=BASE_TIME,
        consecutive_failures=1,
        notification_sent_at=None,
    )
    defaults.update(overrides)
    return PolicyState(**defaults)


def test_decision_rejects_retry_without_time():
    with pytest.raises(ValueError, match="scheduled time"):
        Decision(
            decision_type=DecisionType.RETRY_SCHEDULED,
            rule_id="X",
            rule_description="bad",
        )


def test_decision_rejects_stop_without_escalation():
    """'Compliant escalation' means a stop must name a next action, not merely give up."""
    with pytest.raises(ValueError, match="escalation action"):
        Decision(
            decision_type=DecisionType.STOPPED_ATTEMPTS_EXHAUSTED,
            rule_id="X",
            rule_description="bad",
        )


def test_baseline_retries_on_recoverable_failure(config):
    decision = BaselinePolicy().decide(make_state(), config)
    assert decision.decision_type == DecisionType.RETRY_SCHEDULED
    assert decision.scheduled_retry_at is not None
    assert decision.rule_id == "BASE-001"


def test_baseline_respects_24h_notification_floor(config):
    """Even the fixed-cadence baseline may not schedule a debit inside the RBI timing floor."""
    decision = BaselinePolicy().decide(make_state(), config)
    gap = decision.scheduled_retry_at - decision.notification_to_send_at
    assert gap >= timedelta(hours=24)


def test_baseline_stops_at_attempt_cap(config):
    """A20: Razorpay's documented halt condition is 4 failed attempts."""
    max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]
    decision = BaselinePolicy().decide(make_state(attempt_number=max_attempts), config)
    assert decision.decision_type == DecisionType.STOPPED_ATTEMPTS_EXHAUSTED
    assert decision.escalation_action == EscalationAction.NOTIFY_CUSTOMER_MANUAL_PAYMENT


def test_baseline_stops_on_expired_mandate_with_remandate_escalation(config):
    decision = BaselinePolicy().decide(
        make_state(failure_class=FailureClass.MANDATE_EXPIRED), config
    )
    assert decision.decision_type == DecisionType.STOPPED_UNRECOVERABLE
    assert decision.escalation_action == EscalationAction.REQUEST_REMANDATE


def test_baseline_stops_on_revoked_mandate_with_no_action(config):
    """A revoked mandate means the customer withdrew consent -- there is no compliant next step."""
    decision = BaselinePolicy().decide(
        make_state(failure_class=FailureClass.MANDATE_REVOKED), config
    )
    assert decision.decision_type == DecisionType.STOPPED_UNRECOVERABLE
    assert decision.escalation_action == EscalationAction.NO_ACTION_POSSIBLE


def test_baseline_ignores_failure_class_when_scheduling(config):
    """The baseline is deliberately 'rigid': same cadence regardless of why the payment failed.

    This is the behaviour Razorpay's own Intelligent Retry Engine materials criticise, and it is
    what the adaptive policy must beat.
    """
    a = BaselinePolicy().decide(make_state(failure_class=FailureClass.INSUFFICIENT_FUNDS), config)
    b = BaselinePolicy().decide(make_state(failure_class=FailureClass.NPCI_CONGESTION), config)
    assert a.scheduled_retry_at == b.scheduled_retry_at


def test_external_stub_refuses_to_run():
    """A26: the stub proves the interface generalises; it is not evidence of a benchmark."""
    with pytest.raises(NotImplementedError, match="A26"):
        ExternalPolicyStub().decide(make_state(), load_config())
