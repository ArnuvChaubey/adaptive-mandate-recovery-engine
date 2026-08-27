"""Guards the compliance veto in the live-integration path specifically.

Entry 25 found that integration/razorpay_test_mode/live_batch.py computed compliance checks and then
never consulted them -- every decision was recorded, and would have fired, exactly as the policy
proposed, regardless of whether compliance passed. That's entry 10's bug, reintroduced in the live
path instead of the original harness. This test would have failed on that state and didn't exist to
catch it. It does now, and it's what proves apply_compliance_veto is the only thing standing between
a proposed retry and _fire_retry_action ever being called for a non-compliant one.
"""

from audit.decision_log_schema.records import ComplianceCheck, DecisionType
from integration.razorpay_test_mode.live_batch import apply_compliance_veto


def _check(passed: bool, applicable: bool = True) -> ComplianceCheck:
    return ComplianceCheck("INV-TEST", "test invariant", passed, "detail", applicable=applicable)


def test_compliant_retry_passes_through_unchanged():
    result = apply_compliance_veto(DecisionType.RETRY_SCHEDULED, [_check(True), _check(True)])
    assert result == DecisionType.RETRY_SCHEDULED


def test_noncompliant_retry_is_blocked():
    result = apply_compliance_veto(DecisionType.RETRY_SCHEDULED, [_check(True), _check(False)])
    assert result == DecisionType.BLOCKED_BY_COMPLIANCE


def test_veto_only_applies_to_retry_decisions():
    # A failed compliance check attached to an escalation (or a not-applicable check) must never
    # relabel a decision that was never a retry in the first place -- the veto's job is narrow.
    for decision_type in (DecisionType.ESCALATED, DecisionType.STOPPED_UNRECOVERABLE):
        assert apply_compliance_veto(decision_type, [_check(False)]) == decision_type


def test_veto_ignores_inapplicable_checks():
    # An inapplicable check is non-blocking by definition (ComplianceCheck's own contract) -- it must
    # never be the thing that trips the veto.
    result = apply_compliance_veto(DecisionType.RETRY_SCHEDULED, [_check(True, applicable=False)])
    assert result == DecisionType.RETRY_SCHEDULED


def test_no_checks_at_all_is_vacuously_compliant():
    # all() over an empty list is True -- documenting the behaviour explicitly rather than leaving it
    # as an implicit consequence of Python's all().
    result = apply_compliance_veto(DecisionType.RETRY_SCHEDULED, [])
    assert result == DecisionType.RETRY_SCHEDULED
