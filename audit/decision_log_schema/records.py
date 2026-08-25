"""The audit trail.

Every retry / stop / escalate decision any policy makes writes exactly one record here, tagged with
the rule that produced it. Two properties matter and are non-negotiable:

1. **Independent of the LLM.** The narrator (Milestone 5) reads these records to produce human
   explanations; it never writes to them and never influences a decision. Delete narrator/ entirely
   and the audit trail is unchanged and still complete. This boundary is the evidence for Track 03's
   "AI judgment -- the right tool in the right place, and where you chose not to use one".
2. **Same schema for simulated and live events.** `source` distinguishes them so a reader can never
   mistake a simulated batch statistic for a real-money one, but the structure is identical, so the
   same queries work over both.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class DecisionType(str, Enum):
    RETRY_SCHEDULED = "retry_scheduled"
    STOPPED_ATTEMPTS_EXHAUSTED = "stopped_attempts_exhausted"
    STOPPED_UNRECOVERABLE = "stopped_unrecoverable"
    ESCALATED = "escalated"
    # A retry the policy proposed but compliance refused to execute. Recorded rather than hidden:
    # a policy that repeatedly proposes non-compliant actions is a policy with a real defect, and
    # that defect should be visible in the audit trail and measurable in the metrics.
    BLOCKED_BY_COMPLIANCE = "blocked_by_compliance"


class EscalationAction(str, Enum):
    """What a policy does instead of retrying. The rubric asks for *compliant escalation*, which
    means the stop decision must name a next action, not merely give up."""
    REQUEST_REMANDATE = "request_remandate"          # expired mandate: authorization must be renewed
    NOTIFY_CUSTOMER_MANUAL_PAYMENT = "notify_customer_manual_payment"
    NO_ACTION_POSSIBLE = "no_action_possible"        # revoked: customer withdrew consent
    # Above the no-OTP ceiling (A6) a recurring debit legally requires additional factor
    # authentication, so it cannot be auto-retried at all -- the compliant move is to ask the
    # customer to re-authenticate rather than to fire an attempt that must be refused.
    REQUEST_ADDITIONAL_AUTHENTICATION = "request_additional_authentication"


class Source(str, Enum):
    SIMULATION = "simulation"
    LIVE_TEST_MODE = "live_test_mode"


@dataclass(frozen=True)
class ComplianceCheck:
    """One invariant evaluated against a proposed decision.

    Recording checks that *passed* matters as much as ones that blocked something: it's the
    difference between "we never violated the rule" and "we never tested the rule."

    `applicable` distinguishes a rule that was tested and satisfied from one that didn't apply to
    this decision at all. Both are non-blocking, but conflating them makes the audit trail read
    misleadingly -- an escalation triggered *because* an amount exceeds the OTP ceiling should not
    also report "OTP ceiling: satisfied".
    """
    invariant_id: str
    description: str
    passed: bool
    detail: str = ""
    applicable: bool = True


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    mandate_id: str
    policy_name: str
    decision_type: DecisionType
    rule_id: str                      # which rule in the policy fired -- the auditable link
    rule_description: str
    failure_class: str
    attempt_number: int
    decided_at: datetime
    source: Source
    scheduled_retry_at: datetime | None = None
    escalation_action: EscalationAction | None = None
    compliance_checks: list[ComplianceCheck] = field(default_factory=list)
    amount_inr: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decided_at"] = self.decided_at.isoformat()
        d["scheduled_retry_at"] = (
            self.scheduled_retry_at.isoformat() if self.scheduled_retry_at else None
        )
        return d


class DecisionLog:
    """Append-only decision log. Queryable after the fact, serializable to JSONL."""

    def __init__(self) -> None:
        self._records: list[DecisionRecord] = []

    def append(self, record: DecisionRecord) -> None:
        self._records.append(record)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        return iter(self._records)

    @property
    def records(self) -> list[DecisionRecord]:
        return list(self._records)

    def for_mandate(self, mandate_id: str) -> list[DecisionRecord]:
        return [r for r in self._records if r.mandate_id == mandate_id]

    def by_decision_type(self, decision_type: DecisionType) -> list[DecisionRecord]:
        return [r for r in self._records if r.decision_type == decision_type]

    def compliance_failures(self) -> list[DecisionRecord]:
        """Any record where an invariant did not pass. Should always be empty -- a policy is not
        permitted to emit a decision that violates a compliance floor."""
        return [r for r in self._records if any(not c.passed for c in r.compliance_checks)]

    def write_jsonl(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for record in self._records:
                f.write(json.dumps(record.to_json_dict()) + "\n")
