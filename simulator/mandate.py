"""Core data models for the simulator.

A Mandate is a recurring-payment authorization. A FailureEvent is one failed charge attempt
against a mandate, carrying the ground-truth context the evaluation harness later needs to
decide whether a policy's retry was well-placed or wasted.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class FailureClass(str, Enum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    NOTIFICATION_UNDELIVERED = "notification_undelivered"
    NPCI_CONGESTION = "npci_congestion"
    BANK_TECHNICAL_DECLINE = "bank_technical_decline"
    MANDATE_EXPIRED = "mandate_expired"
    MANDATE_REVOKED = "mandate_revoked"


# A19: these two are unrecoverable by any retry-timing strategy, by definition -- an expired or
# revoked mandate has no active authorization to debit against. Policies must stop, not retry.
UNRECOVERABLE_CLASSES = frozenset({
    FailureClass.MANDATE_EXPIRED,
    FailureClass.MANDATE_REVOKED,
})


class AmountType(str, Enum):
    OTT_SUBSCRIPTION = "ott_subscription"
    SIP_INVESTMENT = "sip_investment"
    EMI = "emi"


class IncomeTimingType(str, Enum):
    """A12/A13: population-level salary clustering is reasonably evidenced; individual adherence
    is not. Modeled as a mixture over types rather than one universal payday."""
    CLUSTERED_MONTH_END_OR_1ST = "clustered_month_end_or_1st"
    CLUSTERED_NEAR_7TH = "clustered_near_7th"
    IRREGULAR_NO_CLEAR_CYCLE = "irregular_no_clear_cycle"


@dataclass(frozen=True)
class Mandate:
    mandate_id: str
    amount_inr: float
    amount_type: AmountType
    income_timing_type: IncomeTimingType
    created_at: datetime
    validity_days: int

    @property
    def expires_at_day(self) -> int:
        return self.validity_days


@dataclass(frozen=True)
class FailureEvent:
    """One failed charge attempt. `true_success_probability_at_event` is simulator ground truth --
    never visible to any policy, used only by the evaluation harness to classify wasted attempts
    (A23) after the fact."""

    event_id: str
    mandate: Mandate
    failure_class: FailureClass
    attempt_number: int
    occurred_at: datetime
    true_success_probability_at_event: float
    notification_delivered: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def is_recoverable(self) -> bool:
        return self.failure_class not in UNRECOVERABLE_CLASSES
