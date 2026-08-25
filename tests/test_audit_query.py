"""Tests for natural-language audit interrogation.

The model translates a question into a `QuerySpec`; deterministic code executes it. These tests cover
the two halves separately -- spec validation (can the model smuggle anything past it?) and execution
(does the filter actually filter?) -- because that separation is the entire safety argument.
"""

from audit.query import QuerySpec, execute, validate_spec

RECORDS = [
    {
        "source": "simulation", "decision_type": "blocked_by_compliance", "rule_id": "BASE-001",
        "policy_name": "baseline", "failure_class": "insufficient_funds", "attempt_number": 1,
        "amount_inr": 26_287.36, "escalation_action": None,
        "compliance_checks": [
            {"invariant_id": "INV-RBI-OTP-CEILING", "passed": False, "applicable": True},
            {"invariant_id": "INV-RBI-6a-NOTIFICATION-TIMING", "passed": True, "applicable": True},
        ],
    },
    {
        "source": "simulation", "decision_type": "escalated", "rule_id": "ADAPT-002",
        "policy_name": "adaptive", "failure_class": "insufficient_funds", "attempt_number": 1,
        "amount_inr": 41_000.0, "escalation_action": "request_additional_authentication",
        "compliance_checks": [
            {"invariant_id": "INV-RBI-OTP-CEILING", "passed": True, "applicable": False},
        ],
    },
    {
        "source": "live_test_mode", "decision_type": "retry_scheduled", "rule_id": "ADAPT-004",
        "policy_name": "adaptive", "failure_class": "insufficient_funds", "attempt_number": 1,
        "amount_inr": 199.0, "escalation_action": None,
        "compliance_checks": [
            {"invariant_id": "INV-RBI-OTP-CEILING", "passed": True, "applicable": True},
        ],
    },
]


# ---------------------------------------------------------------------------------------------
# Spec validation -- what the model is allowed to ask for
# ---------------------------------------------------------------------------------------------

def test_accepts_a_well_formed_spec():
    spec = validate_spec({"decision_type": "escalated", "min_amount_inr": 15000})
    assert spec.valid
    assert spec.decision_type == "escalated"


def test_rejects_unknown_field_rather_than_ignoring_it():
    """A silently-dropped filter returns a WIDER result set than the question asked for, which in a
    compliance context means quietly answering a different question."""
    spec = validate_spec({"decision_type": "escalated", "merchant_id": "acc_123"})
    assert not spec.valid
    assert "merchant_id" in spec.rejected_reason


def test_rejects_invalid_decision_type():
    spec = validate_spec({"decision_type": "definitely_not_a_real_type"})
    assert not spec.valid
    assert "invalid decision_type" in spec.rejected_reason


def test_rejects_invalid_source():
    spec = validate_spec({"source": "production"})
    assert not spec.valid


def test_rejects_invalid_escalation_action():
    spec = validate_spec({"escalation_action": "send_debt_collector"})
    assert not spec.valid


# ---------------------------------------------------------------------------------------------
# Execution -- deterministic, no model involvement
# ---------------------------------------------------------------------------------------------

def test_filters_by_decision_type():
    assert len(execute(QuerySpec(decision_type="escalated"), RECORDS)) == 1


def test_filters_by_amount_threshold():
    matched = execute(QuerySpec(min_amount_inr=15_000), RECORDS)
    assert len(matched) == 2
    assert all(r["amount_inr"] >= 15_000 for r in matched)


def test_filters_by_source_separating_live_from_simulated():
    """The distinction that must never blur: a live record is an integration proof, a simulated one
    is a statistic."""
    assert len(execute(QuerySpec(source="live_test_mode"), RECORDS)) == 1
    assert len(execute(QuerySpec(source="simulation"), RECORDS)) == 2


def test_compliance_failed_finds_only_actual_violations():
    matched = execute(QuerySpec(compliance_failed=True), RECORDS)
    assert len(matched) == 1
    assert matched[0]["rule_id"] == "BASE-001"


def test_not_applicable_check_is_not_a_violation():
    """The escalated record has an OTP check marked passed-but-not-applicable. It must not be
    returned as a compliance failure -- that would report the correct behaviour as a breach."""
    assert RECORDS[1] not in execute(QuerySpec(compliance_failed=True), RECORDS)


def test_filters_combine_as_conjunction():
    matched = execute(
        QuerySpec(policy_name="adaptive", min_amount_inr=15_000, decision_type="escalated"),
        RECORDS,
    )
    assert len(matched) == 1


def test_empty_spec_returns_everything():
    assert len(execute(QuerySpec(), RECORDS)) == len(RECORDS)
