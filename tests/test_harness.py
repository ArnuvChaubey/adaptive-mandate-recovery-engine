"""Harness-level tests.

The one asserted here that matters most: mandates are matched across policies. Found broken while
building the oracle -- 30 of 50 "same" mandates got a different failure class between a baseline run
and an adaptive run of the identical seed, because both drew from one shared, continuously-advancing
RNG stream that diverged the moment the two policies took different numbers of attempts. See
docs/build_log.md entry 21.
"""

from simulator.batch import generate_mandates
from simulator.config_loader import load_config
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.baseline_policy.policy import BaselinePolicy
from policies.oracle_policy.policy import OraclePolicy
from eval.harness import run_policy_on_batch


def _first_attempt_failure_classes(result) -> dict[str, str]:
    return {r.mandate_id: r.failure_class for r in result.decision_log if r.attempt_number == 1}


def test_same_seed_gives_every_policy_the_same_mandate_worlds():
    """The regression this fix exists for. Same seed, three policies that take very different
    numbers of attempts (baseline never escalates for compliance, oracle rarely wastes an attempt,
    adaptive does both) -- every mandate must still start in the identical world."""
    config = load_config()
    mandates = generate_mandates(200, seed=1, config=config)

    results = {
        "baseline": run_policy_on_batch(BaselinePolicy(), mandates, config, seed=1),
        "adaptive": run_policy_on_batch(AdaptivePolicy(), mandates, config, seed=1),
        "oracle": run_policy_on_batch(OraclePolicy(), mandates, config, seed=1),
    }

    baseline_classes = _first_attempt_failure_classes(results["baseline"])
    assert len(baseline_classes) > 100  # sanity: the batch actually ran

    for name in ("adaptive", "oracle"):
        other = _first_attempt_failure_classes(results[name])
        mismatches = [k for k in baseline_classes if baseline_classes.get(k) != other.get(k)]
        assert not mismatches, (
            f"{name} disagreed with baseline on {len(mismatches)} mandates' failure class -- "
            "the shared world is supposed to be policy-independent"
        )


def test_a_later_mandate_is_unaffected_by_an_earlier_mandates_attempt_count():
    """The mechanism directly, not just its cross-policy consequence: mandate 9's world must not
    depend on how many attempts mandates 0-8 took. Baseline and oracle take very different numbers
    of attempts for early mandates (oracle rarely wastes one, baseline sometimes gets blocked by
    compliance and stops immediately) -- if the old shared, continuously-advancing stream were still
    in place, that divergence would have already thrown off every mandate after it.

    Note this does NOT mean a mandate's world is stable if it's run as a different-sized subset --
    mandate_index is positional within whatever list is passed to a given call, not a durable
    per-mandate identity. The real and only guarantee is: same seed, same full mandate list, same
    position -> same world, regardless of which policy is doing the choosing. That's what's checked.
    """
    config = load_config()
    mandates = generate_mandates(10, seed=7, config=config)

    baseline_run = run_policy_on_batch(BaselinePolicy(), mandates, config, seed=7)
    oracle_run = run_policy_on_batch(OraclePolicy(), mandates, config, seed=7)

    late_mandate_id = mandates[-1].mandate_id
    baseline_late = [r for r in baseline_run.decision_log if r.mandate_id == late_mandate_id]
    oracle_late = [r for r in oracle_run.decision_log if r.mandate_id == late_mandate_id]

    assert baseline_late and oracle_late
    assert baseline_late[0].failure_class == oracle_late[0].failure_class
    assert baseline_late[0].amount_inr == oracle_late[0].amount_inr


def test_a_run_is_reproducible_from_its_seed():
    """Central to the whole project's reproducibility claim: same seed, same policy, same mandates
    -> byte-identical decisions, every time. The per-mandate reseeding must not introduce any
    dependence on call order or external state."""
    config = load_config()
    mandates = generate_mandates(30, seed=3, config=config)

    run_a = run_policy_on_batch(AdaptivePolicy(), mandates, config, seed=3)
    run_b = run_policy_on_batch(AdaptivePolicy(), mandates, config, seed=3)

    a = [(r.mandate_id, r.decision_type, r.rule_id, r.scheduled_retry_at) for r in run_a.decision_log]
    b = [(r.mandate_id, r.decision_type, r.rule_id, r.scheduled_retry_at) for r in run_b.decision_log]
    assert a == b
