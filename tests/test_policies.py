"""Policy contract and baseline behaviour tests."""

from datetime import datetime, timedelta

import pytest

from audit.decision_log_schema.records import DecisionType, EscalationAction
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.baseline_policy.policy import BaselinePolicy
from policies.external_policy_stub.policy import ExternalPolicyStub
from policies.policy_interface.base import Decision, MandateView, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass, IncomeTimingType, Mandate

BASE_TIME = datetime(2026, 3, 1, 12, 0)


@pytest.fixture
def config():
    return load_config()


def make_state(**overrides) -> PolicyState:
    mandate = overrides.pop("mandate", None) or MandateView(
        mandate_id="m1",
        amount_inr=500.0,
        amount_type=AmountType.OTT_SUBSCRIPTION,
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


# --------------------------------------------------------------------------------------------
# Non-circularity guard
# --------------------------------------------------------------------------------------------

def test_policy_state_cannot_expose_individual_income_timing():
    """The structural guarantee behind every lift number this project reports.

    A13: population-level salary clustering is evidenced, but whether *this* customer is paid on the
    7th is not knowable from any public source. If a policy could read `income_timing_type` it would
    be reading simulator ground truth, and the measured lift would be meaningless.

    So the guarantee is enforced by the type, not by reviewer trust: the field must not exist on the
    view policies receive.
    """
    assert not hasattr(MandateView(
        mandate_id="m1",
        amount_inr=1.0,
        amount_type=AmountType.OTT_SUBSCRIPTION,
        created_at=BASE_TIME,
        validity_days=1,
    ), "income_timing_type")

    full = Mandate(
        mandate_id="m1",
        amount_inr=1.0,
        amount_type=AmountType.OTT_SUBSCRIPTION,
        income_timing_type=IncomeTimingType.CLUSTERED_NEAR_7TH,
        created_at=BASE_TIME,
        validity_days=1,
    )
    assert hasattr(full, "income_timing_type"), "simulator ground truth should still carry it"
    assert not hasattr(MandateView.from_mandate(full), "income_timing_type")


# --------------------------------------------------------------------------------------------
# Adaptive policy
# --------------------------------------------------------------------------------------------

def test_adaptive_escalates_above_otp_ceiling_instead_of_retrying(config):
    """A6: above the ceiling an auto-debit legally requires re-authentication, so proposing a retry
    just burns an attempt on something that must be refused."""
    big = MandateView(
        mandate_id="m2",
        amount_inr=30_000.0,
        amount_type=AmountType.EMI,
        created_at=BASE_TIME,
        validity_days=365,
    )
    decision = AdaptivePolicy().decide(make_state(mandate=big), config)
    assert decision.decision_type == DecisionType.ESCALATED
    assert decision.escalation_action == EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION
    assert decision.scheduled_retry_at is None


def test_adaptive_waits_for_income_event_on_insufficient_funds(config):
    """The population-level bet (A12). Must land later than the baseline's next-day retry."""
    state = make_state(failure_class=FailureClass.INSUFFICIENT_FUNDS)
    adaptive = AdaptivePolicy().decide(state, config)
    baseline = BaselinePolicy().decide(state, config)
    assert adaptive.rule_id == "ADAPT-004"
    assert adaptive.scheduled_retry_at > baseline.scheduled_retry_at


def test_adaptive_does_not_retry_inside_congestion_window(config):
    """A7: the documented NPCI deprioritisation window is 10:00-13:00."""
    state = make_state(
        failure_class=FailureClass.NPCI_CONGESTION,
        failed_at=datetime(2026, 3, 1, 11, 0),
    )
    decision = AdaptivePolicy().decide(state, config)
    retry_hour = decision.scheduled_retry_at.hour
    assert not (10 <= retry_hour < 13), f"scheduled into the congestion window at {retry_hour}:00"


def test_adaptive_respects_24h_notification_floor(config):
    """Belt and braces: the policy proposes compliant decisions, and compliance/ still vetoes."""
    for failure_class in FailureClass:
        if failure_class in (FailureClass.MANDATE_EXPIRED, FailureClass.MANDATE_REVOKED):
            continue
        decision = AdaptivePolicy().decide(make_state(failure_class=failure_class), config)
        if decision.decision_type == DecisionType.RETRY_SCHEDULED:
            gap = decision.scheduled_retry_at - decision.notification_to_send_at
            assert gap >= timedelta(hours=24), f"{failure_class.value} violated the floor"


def test_adaptive_uses_same_attempt_cap_as_baseline(config):
    """Adaptive must win by placing the same finite budget better, never by taking more shots."""
    max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]
    decision = AdaptivePolicy().decide(make_state(attempt_number=max_attempts), config)
    assert decision.decision_type == DecisionType.STOPPED_ATTEMPTS_EXHAUSTED


def test_adaptive_differentiates_timing_by_failure_class(config):
    """The core behavioural difference from baseline: same inputs except the decline reason should
    produce different schedules."""
    funds = AdaptivePolicy().decide(
        make_state(failure_class=FailureClass.INSUFFICIENT_FUNDS), config
    )
    technical = AdaptivePolicy().decide(
        make_state(failure_class=FailureClass.BANK_TECHNICAL_DECLINE), config
    )
    assert funds.scheduled_retry_at != technical.scheduled_retry_at
    assert funds.rule_id != technical.rule_id
