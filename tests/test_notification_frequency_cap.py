"""Guards the notification-frequency cap: unit tests on the check itself, then a property test that
runs every shipped policy through full multi-attempt sequences and confirms the structural claim in
`check_notification_frequency_cap`'s docstring is actually true, not just argued.

No source in this project's research names a maximum notification count -- unlike A5 (a cited timing
floor), this cap has no regulatory citation, and that is stated in the invariant itself rather than
invented. It is derived from A20 (the cited 4-attempt halt): a retry can only be proposed below the
attempt cap, and the attempt-exhausted decision sends no notification, so max_attempts - 1 is a
consequence of an already-frozen fact, not a new independently-sourced number.
"""

from datetime import datetime

from compliance.invariants.rules import (
    ProposedDecision,
    check_notification_frequency_cap,
)
from eval.harness import run_policy_on_batch
from policies.adaptive_hedged_policy.policy import AdaptiveHedgedPolicy
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.baseline_policy.policy import BaselinePolicy
from policies.compliance_aware_baseline.policy import ComplianceAwareBaselinePolicy
from simulator.batch import generate_mandates
from simulator.config_loader import load_config

CAP = 3  # max_attempts (4, A20) - 1, since the final attempt-exhausted decision sends no notification


def _proposed(is_new: bool, prior: int) -> ProposedDecision:
    return ProposedDecision(
        mandate_id="m1",
        amount_inr=1000.0,
        scheduled_retry_at=datetime(2026, 9, 1) if is_new else None,
        notification_sent_at=datetime(2026, 8, 30) if is_new else None,
        is_new_notification=is_new,
        prior_notifications_sent=prior,
    )


def test_under_cap_passes():
    config = load_config()
    check = check_notification_frequency_cap(_proposed(is_new=True, prior=1), config)
    assert check.passed
    assert check.applicable


def test_at_the_cap_boundary_passes():
    """prior=2 + this one = 3 = CAP exactly. The boundary must not be off by one in either direction."""
    config = load_config()
    check = check_notification_frequency_cap(_proposed(is_new=True, prior=CAP - 1), config)
    assert check.passed


def test_over_cap_fails():
    config = load_config()
    check = check_notification_frequency_cap(_proposed(is_new=True, prior=CAP), config)
    assert not check.passed
    assert f"of at most {CAP}" in check.detail


def test_not_applicable_when_no_new_notification_regardless_of_prior_count():
    """A decision that carries forward a prior notification timestamp for the 24h-floor check, but
    isn't itself sending anything new, must never be blocked by this invariant -- even if the prior
    count already sits at the cap."""
    config = load_config()
    check = check_notification_frequency_cap(_proposed(is_new=False, prior=CAP), config)
    assert check.passed
    assert not check.applicable


def test_cap_is_derived_from_the_configured_attempt_cap_not_hardcoded():
    """If A20's max_attempts ever changes, this invariant's cap must move with it, not silently
    stay pinned to today's value of 3."""
    config = load_config()
    real_max = config["retry_policy_shared"]["max_attempts"]["value"]
    modified = {**config, "retry_policy_shared": {
        **config["retry_policy_shared"],
        "max_attempts": {**config["retry_policy_shared"]["max_attempts"], "value": real_max + 2},
    }}
    check = check_notification_frequency_cap(_proposed(is_new=True, prior=real_max), modified, )
    assert check.passed, "raising max_attempts must raise the derived notification cap with it"


def test_every_shipped_policy_never_exceeds_the_cap_across_full_sequences():
    """The property test: not "the check works," but "no shipped policy, run through the real
    multi-attempt harness across many mandates and seeds, ever produces more than CAP notifications
    for any single mandate." This is what makes the invariant's docstring claim ("structural in
    every shipped policy already") a verified fact rather than an assertion.
    """
    config = load_config()
    policies = [
        BaselinePolicy(), ComplianceAwareBaselinePolicy(), AdaptivePolicy(), AdaptiveHedgedPolicy(),
    ]
    violations = []
    for policy in policies:
        for seed in (1, 2, 3):
            mandates = generate_mandates(n=150, seed=seed, config=config)
            result = run_policy_on_batch(policy, mandates, config, seed)
            counts: dict[str, int] = {}
            for record in result.decision_log:
                if record.scheduled_retry_at is not None and record.decision_type.value == "retry_scheduled":
                    counts[record.mandate_id] = counts.get(record.mandate_id, 0) + 1
            for mandate_id, count in counts.items():
                if count > CAP:
                    violations.append((policy.name, seed, mandate_id, count))

    assert not violations, (
        f"{len(violations)} mandate(s) received more than {CAP} notifications: {violations[:5]} "
        f"-- the structural claim in check_notification_frequency_cap's docstring is false"
    )
