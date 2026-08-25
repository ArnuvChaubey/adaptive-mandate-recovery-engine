"""Compliance invariant tests.

The requirement from the implementation plan: these must FAIL when an invariant is deliberately
violated. A check that passes everything proves nothing -- each test here constructs a decision that
genuinely breaks the rule and asserts the invariant catches it.
"""

from datetime import datetime, timedelta

import pytest

from compliance.invariants.rules import (
    INVARIANT_NOTIFICATION_TIMING,
    INVARIANT_OTP_CEILING,
    ProposedDecision,
    check_notification_timing,
    check_otp_ceiling,
    evaluate_all,
    is_compliant,
)
from simulator.config_loader import load_config

BASE_TIME = datetime(2026, 3, 1, 12, 0)


@pytest.fixture
def config():
    return load_config()


def test_notification_timing_passes_at_exactly_24h(config):
    """RBI Clause 6(a) says 'at least 24 hours', so exactly 24h is compliant."""
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=500.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=24),
        notification_sent_at=BASE_TIME,
    )
    assert check_notification_timing(proposed, config).passed


def test_notification_timing_fails_below_24h(config):
    """The deliberate violation: a retry scheduled 23h after the notification."""
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=500.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=23),
        notification_sent_at=BASE_TIME,
    )
    check = check_notification_timing(proposed, config)
    assert not check.passed
    assert check.invariant_id == INVARIANT_NOTIFICATION_TIMING


def test_notification_timing_fails_when_no_notification_sent(config):
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=500.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=48),
        notification_sent_at=None,
    )
    assert not check_notification_timing(proposed, config).passed


def test_notification_timing_not_applicable_to_stop_decisions(config):
    """A stop decision schedules no debit, so the timing floor can't be violated."""
    proposed = ProposedDecision(
        mandate_id="m1", amount_inr=500.0, scheduled_retry_at=None, notification_sent_at=None
    )
    assert check_notification_timing(proposed, config).passed


def test_otp_ceiling_passes_under_limit(config):
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=14_999.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=24),
        notification_sent_at=BASE_TIME,
    )
    assert check_otp_ceiling(proposed, config).passed


def test_otp_ceiling_fails_over_limit(config):
    """The deliberate violation: an auto-retry above the no-OTP ceiling."""
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=25_000.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=24),
        notification_sent_at=BASE_TIME,
    )
    check = check_otp_ceiling(proposed, config)
    assert not check.passed
    assert check.invariant_id == INVARIANT_OTP_CEILING


def test_otp_higher_ceiling_applies_to_named_categories(config):
    """A6: insurance / mutual funds / credit-card bills carry a INR 1,00,000 ceiling."""
    proposed = ProposedDecision(
        mandate_id="m1",
        amount_inr=50_000.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=24),
        notification_sent_at=BASE_TIME,
        amount_category="mutual_funds",
    )
    assert check_otp_ceiling(proposed, config).passed


def test_is_compliant_requires_all_invariants(config):
    """One passing invariant must not rescue a decision that breaks another."""
    good_timing_bad_amount = ProposedDecision(
        mandate_id="m1",
        amount_inr=25_000.0,
        scheduled_retry_at=BASE_TIME + timedelta(hours=24),
        notification_sent_at=BASE_TIME,
    )
    assert not is_compliant(good_timing_bad_amount, config)
    assert len(evaluate_all(good_timing_bad_amount, config)) == 2
