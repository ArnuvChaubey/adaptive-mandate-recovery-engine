"""Grounding check for LLM-generated narration.

The narrator is allowed to rephrase; it is not allowed to introduce facts. In a payments context an
invented rupee amount, date, or regulatory claim in a customer-facing message is not a cosmetic
error -- it is a compliance incident.

So every factual token the model emits is checked against the source record before the output is
used. Anything that fails is discarded in favour of the deterministic template. The model gets to be
fluent; it does not get to be authoritative.

This is deliberately a *mechanical* check rather than a second LLM grading the first: a validator
that can itself hallucinate is not a validator.
"""

import re
from dataclasses import dataclass

from audit.decision_log_schema.records import DecisionRecord

# Words a narrator must not use unless the record actually supports them. These are the phrases that
# would turn a description into a promise or a legal claim.
PROHIBITED_CLAIMS = (
    "guarantee",
    "guaranteed",
    "refund",
    "refunded",
    "penalty",
    "penalties",
    "legal action",
    "credit score",
    "blacklist",
    "blocked permanently",
)

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    issues: tuple[str, ...]

    @property
    def summary(self) -> str:
        return "grounded" if self.passed else "; ".join(self.issues)


def _grounded_numbers(record: DecisionRecord) -> set[str]:
    """Every numeric string the record legitimately supports."""
    grounded = {
        str(record.attempt_number),
        f"{record.amount_inr:,.2f}",
        f"{record.amount_inr:.2f}",
        f"{record.amount_inr:,.0f}",
        f"{record.amount_inr:.0f}",
        str(int(record.amount_inr)),
    }
    for dt in (record.decided_at, record.scheduled_retry_at):
        if dt is None:
            continue
        grounded.update({
            f"{dt.year}", f"{dt.day}", f"{dt.month}",
            f"{dt:%d}", f"{dt:%m}", f"{dt:%H}", f"{dt:%M}",
        })
    # Figures quoted inside the rule description and compliance details are part of the record.
    for text in [record.rule_description] + [c.detail for c in record.compliance_checks] + [
        c.description for c in record.compliance_checks
    ]:
        grounded.update(_NUMBER_RE.findall(text))
    # Normalised forms, so "15,000" and "15000" both count as grounded.
    grounded.update({n.replace(",", "") for n in list(grounded)})
    return grounded


def validate(narration: str, record: DecisionRecord) -> ValidationResult:
    issues: list[str] = []
    lowered = narration.lower()

    for phrase in PROHIBITED_CLAIMS:
        if phrase in lowered:
            issues.append(f"contains prohibited claim '{phrase}'")

    grounded = _grounded_numbers(record)
    for number in _NUMBER_RE.findall(narration):
        if number in grounded or number.replace(",", "") in grounded:
            continue
        # Small integers are ordinary prose ("a second attempt"), not factual claims.
        bare = number.replace(",", "")
        if bare.isdigit() and int(bare) <= 12:
            continue
        issues.append(f"number '{number}' does not appear in the source record")

    if record.rule_id not in narration:
        issues.append(f"does not cite the rule that fired ({record.rule_id})")

    return ValidationResult(passed=not issues, issues=tuple(issues))
