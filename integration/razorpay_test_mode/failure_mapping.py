"""Maps Razorpay's documented decline codes onto this project's failure taxonomy.

This is the join between the simulator's six abstract failure classes and what a real acquirer
actually returns. Without it, the taxonomy is an assertion; with it, every class except one is
anchored to a decline code Razorpay publishes.

Source: Razorpay test-card documentation, "Error Scenarios" table (BAD_REQUEST_ERROR and
GATEWAY_ERROR sections), which lists the exact `error_reason` values the API returns and provides a
test card that triggers each one. Those cards are what make this mapping verifiable rather than
assumed -- each row can be exercised end to end against the real test API.

Two honest gaps, stated rather than papered over:

  - `mandate_expired` and `mandate_revoked` have no decline-code equivalent, because they are
    lifecycle states rather than transaction outcomes. They surface as subscription status changes
    (`subscription.halted`, `subscription.cancelled`), not as payment errors.
  - `npci_congestion` has no dedicated Razorpay error code. NPCI's traffic-management framework is
    documented (A7), but a congestion-driven decline arrives disguised as a generic gateway or
    timeout error. This is a real limitation of the mapping and is why A7's magnitude stays a swept
    assumption rather than something we claim to observe.
"""

from simulator.mandate import FailureClass

# Codes from Razorpay's documented "Error Scenarios" table. Each has a published test card, so each
# row of this mapping can be exercised end to end against the real API.
DOCUMENTED_ERROR_REASONS: dict[str, FailureClass | None] = {
    "insufficient_fund": FailureClass.INSUFFICIENT_FUNDS,
    "payment_timed_out": FailureClass.BANK_TECHNICAL_DECLINE,
    "gateway_technical_error": FailureClass.BANK_TECHNICAL_DECLINE,
    "card_declined": FailureClass.BANK_TECHNICAL_DECLINE,
    "card_disabled_for_online_payments": FailureClass.BANK_TECHNICAL_DECLINE,
    "authentication_failed": FailureClass.NOTIFICATION_UNDELIVERED,
    # Deliberately unmapped -- these are customer/input errors, not recoverable payment failures.
    # Retrying an invalid card number is not a recovery strategy, it is a loop.
    "card_number_invalid": None,
    "payment_cancelled": None,
}

# Codes we have actually seen returned by the live test-mode API but which are NOT in the documented
# table and have no test card that triggers them on demand. `server_error` is the code every failed
# subscription-tokenisation attempt returned on Day 2 (docs/build_log.md entry 4) -- real, verifiable
# from the signed webhook payloads in that incident, but not reproducible on request.
#
# Kept separate because "documented and triggerable" and "observed once in the wild" are different
# grades of evidence, and collapsing them would overstate how well this mapping is verified.
OBSERVED_ERROR_REASONS: dict[str, FailureClass | None] = {
    "server_error": FailureClass.BANK_TECHNICAL_DECLINE,
}

ERROR_REASON_TO_FAILURE_CLASS: dict[str, FailureClass | None] = {
    **DOCUMENTED_ERROR_REASONS,
    **OBSERVED_ERROR_REASONS,
}

# Test cards that trigger each documented error, so the mapping can be exercised for real.
TEST_CARDS_BY_ERROR_REASON: dict[str, str] = {
    "insufficient_fund": "4100280000080001",
    "payment_timed_out": "4100280000090000",
    "card_declined": "4100280000060003",
    "card_disabled_for_online_payments": "4100280000030006",
    "gateway_technical_error": "4100280000020007",
    "authentication_failed": "4100280000000009",
    "card_number_invalid": "4100280000010008",
    "payment_cancelled": "4100280000070002",
}


def map_error_reason(error_reason: str | None) -> FailureClass | None:
    """Returns the failure class for a Razorpay decline, or None if it isn't recoverable by retry.

    An unknown code returns None rather than guessing. Silently bucketing an unrecognised decline
    into `bank_technical_decline` would manufacture retries for failures we don't understand, which
    is exactly the behaviour this project argues against.
    """
    if error_reason is None:
        return None
    return ERROR_REASON_TO_FAILURE_CLASS.get(error_reason)
