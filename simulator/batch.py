"""Generates a batch of synthetic mandates.

"Batch" is deliberate: Track 03's bar asks for measured money recovered *across a batch*, not one
cherry-picked case. Everything here is driven by the frozen config and an explicit seeded RNG, so
any cited result regenerates exactly.
"""

from datetime import datetime, timedelta

import numpy as np

from simulator.config_loader import load_config, sample_from_range
from simulator.mandate import AmountType, IncomeTimingType, Mandate

BATCH_EPOCH = datetime(2026, 1, 1)


def _normalized_weights(rng: np.random.Generator, weight_ranges: dict[str, list[float]]) -> np.ndarray:
    """Draws one weight per category from its range, then normalizes.

    The config gives each category an independent range (A33), so draws won't sum to 1 on their own.
    Normalizing preserves their relative proportions without pretending the ranges were jointly
    calibrated -- they weren't, there's no source for them.
    """
    drawn = np.array([sample_from_range(rng, r) for r in weight_ranges.values()])
    return drawn / drawn.sum()


def generate_mandates(n: int, seed: int, config: dict | None = None) -> list[Mandate]:
    config = config or load_config()
    rng = np.random.default_rng(seed)

    amount_cfg = config["mandate_amount_distribution"]
    weight_cfg = amount_cfg["type_mixture_weights"]
    amount_types = [AmountType.OTT_SUBSCRIPTION, AmountType.SIP_INVESTMENT, AmountType.EMI]
    type_weights = _normalized_weights(
        rng, {t.value: weight_cfg[t.value] for t in amount_types}
    )

    income_cfg = config["income_event_population_mixture"]["types"]
    income_types = [IncomeTimingType(t["name"]) for t in income_cfg]
    income_weights = _normalized_weights(
        rng, {t["name"]: t["weight_range"] for t in income_cfg}
    )

    validity_range = config["failure_classes"]["mandate_expired"]["validity_days_range"]

    mandates = []
    for i in range(n):
        amount_type = amount_types[rng.choice(len(amount_types), p=type_weights)]
        band = amount_cfg["bands_inr"][amount_type.value]
        mandates.append(
            Mandate(
                mandate_id=f"mand_{seed}_{i:05d}",
                amount_inr=round(sample_from_range(rng, band), 2),
                amount_type=amount_type,
                income_timing_type=income_types[rng.choice(len(income_types), p=income_weights)],
                created_at=BATCH_EPOCH + timedelta(days=int(rng.integers(0, 30))),
                validity_days=int(sample_from_range(rng, validity_range)),
            )
        )
    return mandates
