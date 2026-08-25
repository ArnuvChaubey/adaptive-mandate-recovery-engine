"""Tests for the adversarial red-team validator.

The validator is the entire reason a language model is allowed near this project's results. If it
rubber-stamps, the red team stops being evidence and becomes decoration -- so these tests exist to
prove it actually rejects things, including the specific rejections observed in live runs.
"""

import pytest

from eval.redteam import ProposedScenario, _declared_ranges, _extract_yaml, validate
from simulator.config_loader import load_config


@pytest.fixture
def config():
    return load_config()


def scenario(**overrides) -> ProposedScenario:
    return ProposedScenario(
        name=overrides.pop("name", "test_attack"),
        probes=overrides.pop("probes", "some assumption"),
        plausibility=overrides.pop("plausibility", "a payments engineer would accept this"),
        overrides=overrides.pop("overrides", {}),
    )


def test_accepts_a_scenario_inside_declared_ranges(config):
    s = validate(scenario(overrides={"escalation.response_rate.range": [0.10, 0.10]}), config)
    assert s.valid, s.rejected_reason


def test_rejects_value_outside_declared_range(config):
    """Moving outside a declared range is moving the goalposts, not stress-testing."""
    s = validate(scenario(overrides={"escalation.response_rate.range": [0.001, 0.001]}), config)
    assert not s.valid
    assert "escapes the declared range" in s.rejected_reason


def test_rejects_nonexistent_path(config):
    """Observed live: the model twice proposed `...types[0].weight_range`, which the override
    mechanism does not support. Silently creating the key would produce a scenario that tests
    nothing while appearing to pass."""
    s = validate(
        scenario(overrides={"income_event_population_mixture.types[0].weight_range": [0.7, 0.7]}),
        config,
    )
    assert not s.valid
    assert "invalid path" in s.rejected_reason


def test_rejects_failure_mix_that_does_not_sum_to_one(config):
    s = validate(scenario(overrides={"failure_class_mix.weights": {
        "insufficient_funds": 0.9, "npci_congestion": 0.9, "notification_undelivered": 0.1,
        "bank_technical_decline": 0.1, "mandate_expired": 0.1, "mandate_revoked": 0.1,
    }}), config)
    assert not s.valid
    assert "sum to" in s.rejected_reason


def test_rejects_scenario_with_no_overrides(config):
    assert not validate(scenario(overrides={}), config).valid


def test_rejects_scenario_with_no_plausibility_argument(config):
    """'Set everything to the worst value' is a tantrum, not an attack. The model must argue that a
    payments engineer would accept the scenario as real."""
    s = validate(scenario(plausibility="  ", overrides={
        "escalation.response_rate.range": [0.10, 0.10]
    }), config)
    assert not s.valid
    assert "plausibility" in s.rejected_reason


def test_declared_ranges_finds_swept_parameters(config):
    ranges = _declared_ranges(config)
    assert "escalation.response_rate.range" in ranges
    assert "balance_evolution" not in ranges  # not a `range:` key, correctly not picked up
    assert ranges["escalation.response_rate.range"] == [0.10, 0.40]


def test_extract_yaml_handles_unterminated_fence():
    """Observed live: the first run truncated at max_tokens, so the closing fence never arrived and
    a paired-fence regex returned raw text including ```yaml, which is unparseable."""
    assert _extract_yaml("```yaml\nscenarios: []\n```").strip() == "scenarios: []"
    assert _extract_yaml("```yaml\nscenarios: []").strip() == "scenarios: []"
    assert _extract_yaml("scenarios: []").strip() == "scenarios: []"
