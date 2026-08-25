"""The policy contract.

Every policy implements exactly this interface, and the evaluation harness knows nothing else about
any of them. That is what makes "policy-agnostic evaluation harness" an architectural fact rather
than a marketing claim -- baseline and adaptive are scored by identical code reading identical
records.

A policy's job is to answer one question per failure: retry (and when), or stop (and what to do
instead). Note that "stop and do nothing" is not a valid answer -- the rubric asks for *compliant
escalation*, so a stop decision must name its next action.

Policies never see simulator ground truth. `true_success_probability_at_event` exists on the failure
event for the evaluation harness's benefit only; a policy that read it would be cheating, and the
state object handed to `decide()` deliberately does not carry it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from audit.decision_log_schema.records import DecisionType, EscalationAction
from simulator.mandate import AmountType, FailureClass, Mandate


@dataclass(frozen=True)
class MandateView:
    """The redacted view of a mandate that policies are permitted to see.

    This type exists to make non-circularity *structural* rather than a matter of good intentions.
    The full `Mandate` carries `income_timing_type` -- the customer's actual salary-cycle pattern --
    which is exactly the ground truth A13 says no real system could know. Handing policies the full
    object would mean the adaptive policy *could* read the answer sheet, and a reviewer would have
    to take our word that it doesn't.

    So it cannot. The field is not on this type, and `from_mandate` is the only way in.
    """
    mandate_id: str
    amount_inr: float
    amount_type: AmountType
    created_at: datetime
    validity_days: int

    @classmethod
    def from_mandate(cls, mandate: Mandate) -> "MandateView":
        return cls(
            mandate_id=mandate.mandate_id,
            amount_inr=mandate.amount_inr,
            amount_type=mandate.amount_type,
            created_at=mandate.created_at,
            validity_days=mandate.validity_days,
        )


@dataclass(frozen=True)
class PolicyState:
    """Everything a policy is allowed to know at decision time.

    Deliberately excludes ground-truth success probability, the simulated balance, and the
    customer's individual income-timing type -- a real recovery system knows the failure class, the
    amount, the history, and the clock, and nothing else.
    """
    mandate: MandateView
    failure_class: FailureClass
    attempt_number: int
    failed_at: datetime
    consecutive_failures: int
    notification_sent_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    decision_type: DecisionType
    rule_id: str                 # the auditable link between a decision and the rule that made it
    rule_description: str
    scheduled_retry_at: datetime | None = None
    escalation_action: EscalationAction | None = None
    notification_to_send_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.decision_type == DecisionType.RETRY_SCHEDULED and self.scheduled_retry_at is None:
            raise ValueError("A retry decision must carry a scheduled time")
        if self.decision_type in (
            DecisionType.STOPPED_UNRECOVERABLE,
            DecisionType.STOPPED_ATTEMPTS_EXHAUSTED,
            DecisionType.ESCALATED,
        ) and self.escalation_action is None:
            raise ValueError(
                "A stop decision must name an escalation action -- 'compliant escalation' means "
                "stopping with a next step, not merely giving up"
            )


class Policy(ABC):
    """The contract. Implement this and the harness can score you."""

    name: str = "unnamed_policy"

    @abstractmethod
    def decide(self, state: PolicyState, config: dict) -> Decision:
        ...
