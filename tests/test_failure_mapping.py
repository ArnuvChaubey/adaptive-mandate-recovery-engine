"""Tests for the Razorpay decline-code -> failure-class mapping.

This mapping is the join between the simulator's abstract taxonomy and what a real acquirer returns.
If it silently mis-buckets a code, the live integration proof stops proving anything.
"""

from integration.razorpay_test_mode.failure_mapping import (
    DOCUMENTED_ERROR_REASONS,
    OBSERVED_ERROR_REASONS,
    ERROR_REASON_TO_FAILURE_CLASS,
    TEST_CARDS_BY_ERROR_REASON,
    map_error_reason,
)
from simulator.mandate import FailureClass


def test_insufficient_fund_maps_to_insufficient_funds():
    assert map_error_reason("insufficient_fund") == FailureClass.INSUFFICIENT_FUNDS


def test_transient_bank_errors_map_to_technical_decline():
    for reason in ("payment_timed_out", "gateway_technical_error", "server_error", "card_declined"):
        assert map_error_reason(reason) == FailureClass.BANK_TECHNICAL_DECLINE, reason


def test_unrecoverable_input_errors_map_to_nothing():
    """Retrying an invalid card number is a loop, not a recovery strategy."""
    assert map_error_reason("card_number_invalid") is None
    assert map_error_reason("payment_cancelled") is None


def test_unknown_code_returns_none_rather_than_guessing():
    """Bucketing an unrecognised decline into 'technical' would manufacture retries for failures we
    do not understand -- exactly the behaviour this project argues against."""
    assert map_error_reason("some_code_razorpay_added_later") is None
    assert map_error_reason(None) is None


def test_every_documented_code_has_a_test_card():
    """Documented codes must be exercisable against the real test API, or the mapping is an
    assertion rather than a verified join."""
    for reason in DOCUMENTED_ERROR_REASONS:
        assert reason in TEST_CARDS_BY_ERROR_REASON, f"{reason} has no test card"


def test_observed_codes_are_kept_separate_from_documented_ones():
    """'Documented and triggerable on demand' and 'observed once in a real payload' are different
    grades of evidence. Merging them would overstate how well the mapping is verified.

    `server_error` is real -- it appeared in every signed webhook from the Day 2 subscription
    tokenisation failures -- but Razorpay publishes no test card that produces it.
    """
    assert "server_error" in OBSERVED_ERROR_REASONS
    assert "server_error" not in DOCUMENTED_ERROR_REASONS
    assert "server_error" not in TEST_CARDS_BY_ERROR_REASON
    # Still mapped for real traffic, just not claimed as reproducible.
    assert map_error_reason("server_error") == FailureClass.BANK_TECHNICAL_DECLINE


def test_lifecycle_classes_are_deliberately_unmapped():
    """mandate_expired / mandate_revoked are lifecycle states, not transaction outcomes -- they
    arrive as subscription status changes, never as payment decline codes. Their absence here is
    intentional and documented, not an oversight."""
    mapped = set(ERROR_REASON_TO_FAILURE_CLASS.values())
    assert FailureClass.MANDATE_EXPIRED not in mapped
    assert FailureClass.MANDATE_REVOKED not in mapped


def test_npci_congestion_has_no_decline_code():
    """A real limitation, asserted so it cannot be quietly 'fixed' by inventing a mapping: NPCI
    congestion arrives disguised as a generic gateway or timeout error. This is why A7's magnitude
    stays a swept assumption rather than something we claim to observe."""
    assert FailureClass.NPCI_CONGESTION not in set(ERROR_REASON_TO_FAILURE_CLASS.values())
