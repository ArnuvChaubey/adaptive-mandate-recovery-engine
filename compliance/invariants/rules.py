"""Hard regulatory floors, enforced independently of any policy.

These live outside `policies/` on purpose: a reviewer can verify that no policy bypasses a
compliance floor by reading this one small module, instead of auditing every policy implementation.
Policies propose decisions; this module gets a veto.

Every invariant here must be traceable to a citable source. An invariant we cannot quote a clause
for does not belong in this file -- that is the mistake A4 represented, and it is documented in
docs/build_log.md entry 8.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from audit.decision_log_schema.records import ComplianceCheck


@dataclass(frozen=True)
class ProposedDecision:
    """What a policy wants to do, before compliance has had a say."""
    mandate_id: str
    amount_inr: float
    scheduled_retry_at: datetime | None
    notification_sent_at: datetime | None
    amount_category: str = "general"


# A6 names three categories that carry the higher INR 1,00,000 no-OTP ceiling: insurance, mutual
# funds, and credit-card bills. Those are RBI's words. This project's product taxonomy uses its own
# names (`ott_subscription`, `sip_investment`, `emi`), and until entry 26 nothing ever translated
# between the two -- so `amount_category` was left at its "general" default everywhere in production
# and the higher-ceiling branch could never fire. A `sip_investment` *is* a mutual-fund product, so
# the branch was dead for exactly the population it was written to serve.
#
# Deliberately partial. `emi` is NOT mapped to `credit_card_bills`: an EMI is a loan instalment, and
# a credit-card bill is a different instrument that happens to also be payable in instalments. A6's
# higher ceiling is a specific regulatory carve-out and guessing an extra category into it would be
# claiming a legal allowance we cannot cite -- the same mistake A4 represented. `ott_subscription`
# maps to nothing for the same reason.
RBI_CATEGORY_BY_AMOUNT_TYPE: dict[str, str] = {
    "sip_investment": "mutual_funds",
}


def rbi_category_for(amount_type_value: str) -> str:
    """Translates a product type into the RBI category A6 speaks in, or 'general' if none applies."""
    return RBI_CATEGORY_BY_AMOUNT_TYPE.get(amount_type_value, "general")


INVARIANT_NOTIFICATION_TIMING = "INV-RBI-6a-NOTIFICATION-TIMING"
INVARIANT_OTP_CEILING = "INV-RBI-OTP-CEILING"


def check_notification_timing(
    proposed: ProposedDecision, config: dict
) -> ComplianceCheck:
    """A5 / RBI E-mandate Framework 2026 Clause 6(a).

    "An issuer shall send a pre-transaction notification to the customer, at least 24 hours prior to
    the actual charge / debit."

    Note precisely what this does and does not require: the obligation is to SEND the notification
    24h ahead. It is not a delivery-confirmation requirement, and non-delivery does not block the
    debit (see the refuted A4). So the invariant is a timing constraint on scheduling.
    """
    cfg = config["failure_classes"]["notification_undelivered"]["min_hours_between_notification_and_debit"]
    min_hours = cfg["value"]
    description = f"No debit may be scheduled within {min_hours}h of the pre-transaction notification being sent"

    if proposed.scheduled_retry_at is None:
        return ComplianceCheck(
            invariant_id=INVARIANT_NOTIFICATION_TIMING,
            description=description,
            passed=True,
            applicable=False,
            detail="No retry scheduled; invariant not applicable",
        )

    if proposed.notification_sent_at is None:
        return ComplianceCheck(
            invariant_id=INVARIANT_NOTIFICATION_TIMING,
            description=description,
            passed=False,
            detail="Retry scheduled with no pre-transaction notification sent at all",
        )

    gap = proposed.scheduled_retry_at - proposed.notification_sent_at
    passed = gap >= timedelta(hours=min_hours)
    return ComplianceCheck(
        invariant_id=INVARIANT_NOTIFICATION_TIMING,
        description=description,
        passed=passed,
        detail=f"Gap of {gap.total_seconds() / 3600:.1f}h against a {min_hours}h floor",
    )


def check_otp_ceiling(proposed: ProposedDecision, config: dict) -> ComplianceCheck:
    """A6 / RBI E-mandate Framework 2026.

    Recurring debits above the ceiling require additional factor authentication, so they cannot be
    auto-retried silently -- they need customer re-authentication, which is an escalation, not a retry.
    """
    cfg = config["compliance_floors"]["otp_free_ceiling_inr"]
    ceiling = cfg["value"]
    if proposed.amount_category in cfg["higher_ceiling_categories"]:
        ceiling = cfg["higher_ceiling_inr"]

    description = f"Auto-debit without additional factor authentication is capped at INR {ceiling:,}"

    # The ceiling constrains *auto-debit attempts*, not decisions in general. A policy that responds
    # to an over-ceiling failure by requesting re-authentication has done exactly the compliant
    # thing; flagging that as a violation would penalise the correct behaviour.
    if proposed.scheduled_retry_at is None:
        return ComplianceCheck(
            invariant_id=INVARIANT_OTP_CEILING,
            description=description,
            passed=True,
            applicable=False,
            detail="No auto-debit scheduled; ceiling not applicable to an escalation decision",
        )

    passed = proposed.amount_inr <= ceiling
    return ComplianceCheck(
        invariant_id=INVARIANT_OTP_CEILING,
        description=description,
        passed=passed,
        detail=f"Amount INR {proposed.amount_inr:,.2f} against a INR {ceiling:,} ceiling",
    )


def apply_compliance_veto(decision_type, checks: list):
    """The veto itself: a non-compliant retry becomes a blocked one, and nothing else changes.

    This lives here rather than in any one caller because it is the enforcement step, and it has now
    been got wrong once in each direction. Entry 10: the harness computed verdicts and executed the
    retry anyway. Entry 25: the live-integration path computed them and never read them at all. Both
    times the checks were correct and the wiring was not, so the single most important property of
    this project -- that a compliance floor is *enforced*, not merely recorded -- depended on each
    caller remembering to apply it identically.

    Three callers now share this exact function: `eval/harness.py`, the live batch, and
    `eval/benchmark.py`. That last one matters for an unobvious reason -- a benchmark that measures a
    slightly different code path than production measures nothing useful.

    Deliberately narrow: only a RETRY_SCHEDULED decision can be vetoed. An escalation or a stop was
    never an auto-debit, so a failing check must not relabel it.
    """
    from audit.decision_log_schema.records import DecisionType

    if decision_type == DecisionType.RETRY_SCHEDULED and not all(c.passed for c in checks):
        return DecisionType.BLOCKED_BY_COMPLIANCE
    return decision_type


ALL_INVARIANTS = (check_notification_timing, check_otp_ceiling)


def evaluate_all(proposed: ProposedDecision, config: dict) -> list[ComplianceCheck]:
    return [check(proposed, config) for check in ALL_INVARIANTS]


def is_compliant(proposed: ProposedDecision, config: dict) -> bool:
    return all(c.passed for c in evaluate_all(proposed, config))
