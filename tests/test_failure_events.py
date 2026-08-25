"""Tests for the six failure-class generators and batch generation.

The reproducibility tests matter as much as the behavioral ones: if a fixed seed stops producing
identical output, every cited result in the README becomes unverifiable.
"""

from datetime import datetime

import numpy as np
import pytest

from simulator.batch import generate_mandates
from simulator.config_loader import load_config
from simulator.failure_events.generators import AttemptContext, success_probability
from simulator.mandate import AmountType, FailureClass, IncomeTimingType, Mandate


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def rng():
    return np.random.default_rng(42)


def make_ctx(**overrides) -> AttemptContext:
    mandate = overrides.pop("mandate", None) or Mandate(
        mandate_id="mand_test",
        amount_inr=500.0,
        amount_type=AmountType.OTT_SUBSCRIPTION,
        income_timing_type=IncomeTimingType.CLUSTERED_NEAR_7TH,
        created_at=datetime(2026, 1, 1),
        validity_days=365,
    )
    defaults = dict(
        mandate=mandate,
        attempt_time=datetime(2026, 3, 15, 15, 0),  # outside the congestion window
        day_index=30,
        balance_inr=1000.0,
        notification_delivered=True,
        consecutive_failures=0,
    )
    defaults.update(overrides)
    return AttemptContext(**defaults)


def test_insufficient_funds_succeeds_when_balance_covers_amount(config, rng):
    ctx = make_ctx(balance_inr=1000.0)
    assert success_probability(FailureClass.INSUFFICIENT_FUNDS, ctx, config, rng) == 1.0


def test_insufficient_funds_near_zero_when_balance_short(config, rng):
    ctx = make_ctx(balance_inr=50.0)
    p = success_probability(FailureClass.INSUFFICIENT_FUNDS, ctx, config, rng)
    assert 0.0 <= p <= 0.1


def test_notification_undelivered_hard_blocks_debit(config, rng):
    """A4/A5: RBI compliance floor -- an undelivered pre-debit notice blocks the debit outright."""
    ctx = make_ctx(notification_delivered=False)
    assert success_probability(FailureClass.NOTIFICATION_UNDELIVERED, ctx, config, rng) == 0.0


def test_notification_delivered_allows_debit(config, rng):
    ctx = make_ctx(notification_delivered=True)
    assert success_probability(FailureClass.NOTIFICATION_UNDELIVERED, ctx, config, rng) == 1.0


def test_congestion_degrades_inside_documented_window(config, rng):
    """A7: 10:00-13:00 is the documented worst window."""
    inside = make_ctx(attempt_time=datetime(2026, 3, 15, 11, 30))
    p = success_probability(FailureClass.NPCI_CONGESTION, inside, config, rng)
    assert p < 1.0


def test_congestion_clean_outside_window(config, rng):
    outside = make_ctx(attempt_time=datetime(2026, 3, 15, 21, 45))
    assert success_probability(FailureClass.NPCI_CONGESTION, outside, config, rng) == 1.0


def test_congestion_degradation_respects_config_bounds(config, rng):
    lo, hi = config["failure_classes"]["npci_congestion"]["success_probability_degradation"]["range"]
    inside = make_ctx(attempt_time=datetime(2026, 3, 15, 11, 0))
    for _ in range(200):
        p = success_probability(FailureClass.NPCI_CONGESTION, inside, config, rng)
        assert (1.0 - hi) - 1e-9 <= p <= (1.0 - lo) + 1e-9


def test_bank_technical_decline_respects_config_bounds(config, rng):
    lo, hi = config["failure_classes"]["bank_technical_decline"]["base_rate"]["range"]
    ctx = make_ctx()
    for _ in range(200):
        p = success_probability(FailureClass.BANK_TECHNICAL_DECLINE, ctx, config, rng)
        assert (1.0 - hi) - 1e-9 <= p <= (1.0 - lo) + 1e-9


def test_expired_mandate_is_unrecoverable(config, rng):
    """A19: definitional -- no authorization exists past expiry."""
    ctx = make_ctx(day_index=400)  # mandate validity is 365
    assert success_probability(FailureClass.MANDATE_EXPIRED, ctx, config, rng) == 0.0


def test_unexpired_mandate_allows_debit(config, rng):
    ctx = make_ctx(day_index=100)
    assert success_probability(FailureClass.MANDATE_EXPIRED, ctx, config, rng) == 1.0


def test_revoked_mandate_unrecoverable_past_threshold(config, rng):
    """A16: config range is [2, 4] consecutive failures, so 4+ always trips it."""
    ctx = make_ctx(consecutive_failures=4)
    assert success_probability(FailureClass.MANDATE_REVOKED, ctx, config, rng) == 0.0


def test_no_revocation_before_threshold(config, rng):
    ctx = make_ctx(consecutive_failures=1)
    assert success_probability(FailureClass.MANDATE_REVOKED, ctx, config, rng) == 1.0


def test_batch_generation_is_reproducible():
    """If this breaks, every cited number in the README becomes unverifiable."""
    a = generate_mandates(n=50, seed=7)
    b = generate_mandates(n=50, seed=7)
    assert [m.mandate_id for m in a] == [m.mandate_id for m in b]
    assert [m.amount_inr for m in a] == [m.amount_inr for m in b]
    assert [m.amount_type for m in a] == [m.amount_type for m in b]


def test_different_seeds_produce_different_batches():
    a = generate_mandates(n=50, seed=1)
    b = generate_mandates(n=50, seed=2)
    assert [m.amount_inr for m in a] != [m.amount_inr for m in b]


def test_batch_amounts_fall_within_configured_bands():
    config = load_config()
    bands = config["mandate_amount_distribution"]["bands_inr"]
    for m in generate_mandates(n=300, seed=3):
        lo, hi = bands[m.amount_type.value]
        assert lo <= m.amount_inr <= hi


def test_config_loader_rejects_unfrozen_config(tmp_path):
    """The freeze check is the anti-circularity guarantee -- it must actually fire."""
    import yaml
    from simulator.config_loader import ConfigNotFrozenError, load_config as load

    bad = tmp_path / "unfrozen.yaml"
    bad.write_text(yaml.safe_dump({"meta": {"frozen": False}}))
    with pytest.raises(ConfigNotFrozenError):
        load(bad)


def test_config_loader_rejects_frozen_without_hash(tmp_path):
    import yaml
    from simulator.config_loader import ConfigNotFrozenError, load_config as load

    bad = tmp_path / "nohash.yaml"
    bad.write_text(yaml.safe_dump({"meta": {"frozen": True, "frozen_commit_hash": None}}))
    with pytest.raises(ConfigNotFrozenError):
        load(bad)
