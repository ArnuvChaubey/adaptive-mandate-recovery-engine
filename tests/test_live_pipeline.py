"""Tests for the live webhook -> decision loop.

The payloads below are **real**: they are the exact shapes Razorpay's test-mode API sent to our
receiver on 2026-08-24, including the `server_error` / `card_mandate_process` decline that turned out
to be a platform-side failure in their own tokenisation step (docs/build_log.md entry 4).

Testing against captured production shapes rather than invented ones is the point -- a fixture we
wrote ourselves would only prove the parser matches our own imagination.
"""

from datetime import datetime

import pytest

from audit.decision_log_schema.records import DecisionType, EscalationAction, Source
from integration.razorpay_test_mode.live_pipeline import process_event
from policies.adaptive_policy.policy import AdaptivePolicy
from simulator.config_loader import load_config


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def policy():
    return AdaptivePolicy()


def payment_failed(error_reason="insufficient_fund", amount=10000, order_id="order_TTg34KIRJGh7Kp"):
    """Shape captured verbatim from a real Razorpay webhook on 2026-08-24."""
    return {
        "entity": "event",
        "account_id": "acc_TTXKn3kKiyMviX",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {"payment": {"entity": {
            "id": "pay_TTgNsuYQ1hLrnE",
            "entity": "payment",
            "amount": amount,
            "currency": "INR",
            "status": "failed",
            "order_id": order_id,
            "method": "card",
            "captured": False,
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Payment failed",
            "error_source": "internal",
            "error_step": "card_mandate_process",
            "error_reason": error_reason,
            "created_at": 1787591039,
        }}},
        "created_at": 1787591039,
    }


def payment_captured(amount=10000):
    return {
        "entity": "event",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {"payment": {"entity": {
            "id": "pay_TTxm4WQEUhcUbv",
            "amount": amount,
            "currency": "INR",
            "status": "captured",
            "order_id": "order_TTxlUF8SurQrqS",
            "captured": True,
            "created_at": 1787652280,
        }}},
        "created_at": 1787652297,
    }


# ---------------------------------------------------------------------------------------------
# Failures produce decisions
# ---------------------------------------------------------------------------------------------

def test_real_insufficient_funds_webhook_produces_a_retry(config, policy):
    result = process_event(payment_failed("insufficient_fund", amount=50_000), config, policy)
    assert result.record is not None
    assert result.record.decision_type == DecisionType.RETRY_SCHEDULED
    assert result.record.failure_class == "insufficient_funds"
    assert result.record.source == Source.LIVE_TEST_MODE
    assert result.record.scheduled_retry_at is not None


def test_the_actual_day2_server_error_maps_and_decides(config, policy):
    """The decline we really received, end to end. It is in OBSERVED_ERROR_REASONS rather than the
    documented table, so this is the one code we mapped from real traffic alone."""
    result = process_event(payment_failed("server_error"), config, policy)
    assert result.record is not None
    assert result.record.failure_class == "bank_technical_decline"
    assert result.record.metadata["razorpay_error_step"] == "card_mandate_process"


def test_over_ceiling_failure_escalates_rather_than_retrying(config, policy):
    """A6 on live data: above INR 15,000 an auto-retry is not legally available."""
    result = process_event(
        payment_failed("insufficient_fund", amount=3_000_000), config, policy  # INR 30,000
    )
    assert result.record.decision_type == DecisionType.ESCALATED
    assert result.record.escalation_action == EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION
    assert result.record.scheduled_retry_at is None


def test_attempt_cap_stops_the_loop(config, policy):
    """A20: the documented 4-attempt halt condition applies to live events too."""
    result = process_event(
        payment_failed("insufficient_fund", amount=50_000), config, policy, attempt_number=4
    )
    assert result.record.decision_type == DecisionType.STOPPED_ATTEMPTS_EXHAUSTED
    assert result.record.escalation_action is not None


# ---------------------------------------------------------------------------------------------
# Non-failures produce no decision
# ---------------------------------------------------------------------------------------------

def test_capture_is_recorded_as_recovery_not_a_decision(config, policy):
    result = process_event(payment_captured(amount=25_000), config, policy)
    assert result.record is None
    assert result.recovered_amount_inr == 250.0


def test_unrecoverable_decline_produces_no_retry(config, policy):
    """Retrying an invalid card number is a loop, not a recovery strategy."""
    result = process_event(payment_failed("card_number_invalid"), config, policy)
    assert result.record is None
    assert "not recoverable" in result.ignored_reason


def test_unknown_event_is_ignored_rather_than_guessed(config, policy):
    """Inventing a decision for an event we don't understand is how a recovery system starts
    retrying things it shouldn't."""
    payload = payment_failed()
    payload["event"] = "payment.dispute.created"
    result = process_event(payload, config, policy)
    assert result.record is None
    assert "carries no decision" in result.ignored_reason


def test_unknown_decline_code_is_ignored_rather_than_bucketed(config, policy):
    result = process_event(payment_failed("some_new_code_razorpay_added"), config, policy)
    assert result.record is None


def test_malformed_payload_does_not_raise(config, policy):
    """Webhook input is attacker-shaped in the general case; a parser that throws is a DoS."""
    result = process_event({"event": "payment.failed", "payload": {}}, config, policy)
    assert result.record is None
    assert result.ignored_reason is not None


# ---------------------------------------------------------------------------------------------
# The loop obeys the same rules as the simulated path
# ---------------------------------------------------------------------------------------------

def test_live_decisions_carry_compliance_checks(config, policy):
    result = process_event(payment_failed("insufficient_fund", amount=50_000), config, policy)
    ids = {c.invariant_id for c in result.record.compliance_checks}
    assert "INV-RBI-6a-NOTIFICATION-TIMING" in ids
    assert "INV-RBI-OTP-CEILING" in ids


def test_live_retry_respects_the_24h_notification_floor(config, policy):
    """RBI Clause 6(a) applies identically to live events -- there is no fast path for real money."""
    result = process_event(payment_failed("insufficient_fund", amount=50_000), config, policy)
    assert all(c.passed for c in result.record.compliance_checks)


def test_terminal_subscription_event_stops_everything(config, policy):
    payload = payment_failed()
    payload["event"] = "subscription.halted"
    result = process_event(payload, config, policy)
    assert result.record.decision_type == DecisionType.STOPPED_UNRECOVERABLE
    assert result.record.escalation_action == EscalationAction.NO_ACTION_POSSIBLE
