"""Loads the frozen simulator config.

Refuses to load an unfrozen config: the anti-circularity requirement means no simulation may run
against ground truth that hasn't been committed and hashed first.
"""

from pathlib import Path
from typing import Any

import numpy as np
import yaml

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "sim_params.yaml"


class ConfigNotFrozenError(RuntimeError):
    pass


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with open(path) as f:
        config = yaml.safe_load(f)

    meta = config.get("meta", {})
    if not meta.get("frozen"):
        raise ConfigNotFrozenError(
            f"{path} has meta.frozen != true. Simulation ground truth must be frozen and committed "
            "before any run, so results can never be attributed to post-hoc parameter tuning."
        )
    if not meta.get("frozen_commit_hash"):
        raise ConfigNotFrozenError(
            f"{path} is marked frozen but has no frozen_commit_hash. The hash is what makes the "
            "freeze auditable -- without it the claim is unverifiable."
        )
    return config


def sample_from_range(rng: np.random.Generator, bounds: list[float]) -> float:
    """Draws a value from an ASSUMPTION-tagged [low, high] range.

    Sensitivity analysis (Milestone 4) sweeps these deliberately rather than sampling; this is the
    within-scenario draw used when a scenario doesn't pin the parameter.
    """
    low, high = bounds
    return float(rng.uniform(low, high))
