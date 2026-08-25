"""Narrator tests.

The important ones are the grounding tests: they prove the validator actually rejects fabricated
facts rather than merely existing. A guard that never fires is indistinguishable from no guard.
"""

from datetime import datetime

import pytest

from audit.decision_log_schema.records import (
    ComplianceCheck,
    DecisionRecord,
    DecisionType,
    EscalationAction,
    Source,
)
from narrator import templates
from narrator.llm_explainer.explainer import Narration, narrate, narrate_with_template
from narrator.validator import validate

BASE_TIME = datetime(2026, 3, 1, 12, 0)


def make_record(**overrides) -> DecisionRecord:
    defaults = dict(
        decision_id="d1",
        mandate_id="mand_1",
        policy_name="adaptive",
        decision_type=DecisionType.RETRY_SCHEDULED,
        rule_id="ADAPT-004",
        rule_description="Insufficient funds: wait until after the next income event",
        failure_class="insufficient_funds",
        attempt_number=1,
        decided_at=BASE_TIME,
        source=Source.SIMULATION,
        scheduled_retry_at=datetime(2026, 3, 29, 14, 0),
        escalation_action=None,
        compliance_checks=[
            ComplianceCheck("INV-RBI-6a-NOTIFICATION-TIMING", "24h floor", True, "Gap of 24.0h")
        ],
        amount_inr=1500.0,
    )
    defaults.update(overrides)
    return DecisionRecord(**defaults)


# ---------------------------------------------------------------------------------------------
# Grounding validator -- must actually reject things
# ---------------------------------------------------------------------------------------------

def test_validator_rejects_invented_amount():
    record = make_record()
    bad = "Rule ADAPT-004 rescheduled the debit. We will collect INR 99,999.00 next week."
    result = validate(bad, record)
    assert not result.passed
    assert any("99,999.00" in issue for issue in result.issues)


def test_validator_rejects_prohibited_claim():
    """A narration promising a refund in a payments context is a compliance incident."""
    record = make_record()
    bad = "Rule ADAPT-004 scheduled a retry and you will receive a refund if it fails."
    result = validate(bad, record)
    assert not result.passed
    assert any("refund" in issue for issue in result.issues)


def test_validator_rejects_missing_rule_citation():
    """Every narration must name the rule that fired -- that link is the audit trail."""
    record = make_record()
    bad = "The payment failed and we will try again later."
    result = validate(bad, record)
    assert not result.passed
    assert any("does not cite the rule" in issue for issue in result.issues)


def test_validator_accepts_grounded_narration():
    record = make_record()
    good = (
        "Rule ADAPT-004 rescheduled the attempt for mandate mand_1 (INR 1,500.00) to 2026-03-29 "
        "after the next likely income event."
    )
    assert validate(good, record).passed


def test_validator_allows_small_ordinal_numbers():
    """'a second attempt' is prose, not a factual claim -- the guard must not be so strict it
    rejects ordinary English."""
    record = make_record()
    assert validate("Rule ADAPT-004 scheduled a 2nd attempt for INR 1,500.00.", record).passed


# ---------------------------------------------------------------------------------------------
# Deterministic templates -- the system must work with no LLM at all
# ---------------------------------------------------------------------------------------------

def test_template_narration_is_grounded_by_construction():
    record = make_record()
    text = templates.internal_explanation(record)
    assert validate(text, record).passed


def test_template_cites_the_rule():
    assert "ADAPT-004" in templates.internal_explanation(make_record())


def test_no_customer_message_for_revoked_mandate():
    """Messaging a customer who withdrew consent is not a compliant action."""
    record = make_record(
        decision_type=DecisionType.STOPPED_UNRECOVERABLE,
        failure_class="mandate_revoked",
        escalation_action=EscalationAction.NO_ACTION_POSSIBLE,
        scheduled_retry_at=None,
        rule_id="ADAPT-001",
    )
    assert templates.customer_message(record) == ""


def test_escalation_produces_actionable_customer_message():
    record = make_record(
        decision_type=DecisionType.ESCALATED,
        escalation_action=EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION,
        scheduled_retry_at=None,
        rule_id="ADAPT-002",
        amount_inr=30_000.0,
    )
    message = templates.customer_message(record)
    assert "authorise" in message.lower()


def test_not_applicable_checks_are_not_reported_as_satisfied():
    """An escalation triggered *because* an amount exceeds the ceiling must not also claim the
    ceiling check was satisfied."""
    record = make_record(
        decision_type=DecisionType.ESCALATED,
        escalation_action=EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION,
        scheduled_retry_at=None,
        rule_id="ADAPT-002",
        amount_inr=30_000.0,
        compliance_checks=[
            ComplianceCheck("INV-RBI-OTP-CEILING", "ceiling", True, "not applicable", applicable=False)
        ],
    )
    assert "INV-RBI-OTP-CEILING" not in templates.internal_explanation(record)


# ---------------------------------------------------------------------------------------------
# The LLM boundary
# ---------------------------------------------------------------------------------------------

def test_narration_never_claims_to_have_influenced_a_decision():
    assert narrate_with_template(make_record()).influenced_decision is False


def test_falls_back_to_template_when_llm_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = narrate(make_record())
    assert result.source == "template"
    assert result.internal_explanation


def test_ungrounded_llm_output_is_discarded(monkeypatch):
    """The whole point of the guard: a hallucination degrades fluency, never correctness."""
    record = make_record()

    class FakeBlock:
        type = "text"
        text = "INTERNAL: Rule ADAPT-004 scheduled a retry of INR 88,888.00.\nCUSTOMER: NONE"

    class FakeMessages:
        def create(self, **kwargs):
            class R:
                content = [FakeBlock()]
            return R()

    class FakeClient:
        messages = FakeMessages()

    result = narrate(record, client=FakeClient())
    assert result.source == "template"
    assert result.validation is not None and not result.validation.passed
    assert "88,888.00" not in result.internal_explanation


def test_grounded_llm_output_is_used(monkeypatch):
    record = make_record()

    class FakeBlock:
        type = "text"
        text = (
            "INTERNAL: Rule ADAPT-004 delayed the retry on mandate mand_1 for INR 1,500.00 "
            "until after the next likely income event.\n"
            "CUSTOMER: We could not collect your payment; we will try again shortly."
        )

    class FakeMessages:
        def create(self, **kwargs):
            class R:
                content = [FakeBlock()]
            return R()

    class FakeClient:
        messages = FakeMessages()

    result = narrate(record, client=FakeClient())
    assert result.source == "llm"
    assert result.validation is not None and result.validation.passed
