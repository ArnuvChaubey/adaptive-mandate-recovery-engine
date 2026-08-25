"""Sensitivity sweep.

The single most important thing this project produces. A lift number computed at one point in a
space of LOW-confidence assumptions is worth very little; what matters is whether the result survives
across the uncertainty we have already declared.

The headline claim this module is designed to support is deliberately conservative:

    "Adaptive policy shows positive lift in X of Y scenarios, ranging from A% to B%,
     including Z% against the strongest baseline we could construct."

Not the maximum. Not the mean. Scenarios where adaptive loses are reported, because a harness that
only ever flatters its own reference policy is not evidence of anything.

    python -m eval.sensitivity
"""

import argparse
import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from eval.harness import run_policy_on_batch
from eval.metrics.definitions import MetricsReport, compute_metrics, recovery_lift
from eval.run_eval import AVAILABLE_POLICIES, REPORTS_DIR
from simulator.batch import generate_mandates
from simulator.config_loader import load_config

SCENARIOS_PATH = Path(__file__).parent.parent / "config" / "scenarios.yaml"


def apply_override(config: dict, dotted_path: str, value: Any) -> None:
    """Sets a value at a dotted path, failing loudly if the path doesn't exist.

    Silently creating a key would mean a typo in scenarios.yaml produces a scenario that quietly
    tests nothing while appearing to pass -- the worst possible failure mode for a sweep whose whole
    job is to be trusted.
    """
    keys = dotted_path.split(".")
    node = config
    for key in keys[:-1]:
        if key not in node:
            raise KeyError(f"Override path '{dotted_path}' does not exist in config (at '{key}')")
        node = node[key]
    if keys[-1] not in node:
        raise KeyError(f"Override path '{dotted_path}' does not exist in config (at '{keys[-1]}')")
    node[keys[-1]] = value


def build_scenario_config(base_config: dict, overrides: dict[str, Any]) -> dict:
    config = copy.deepcopy(base_config)
    for path, value in overrides.items():
        apply_override(config, path, value)
    return config


@dataclass
class ScenarioResult:
    name: str
    probes: str
    reports: dict[str, MetricsReport]

    def lift(self, baseline: str, candidate: str) -> dict[str, float]:
        return recovery_lift(self.reports[baseline], self.reports[candidate])


def run_scenario(
    name: str,
    probes: str,
    config: dict,
    policy_names: list[str],
    seeds: list[int],
    n_mandates: int,
) -> ScenarioResult:
    reports = {}
    for policy_name in policy_names:
        policy = AVAILABLE_POLICIES[policy_name]()
        mandate_outcomes, attempt_outcomes = [], []
        for seed in seeds:
            mandates = generate_mandates(n=n_mandates, seed=seed, config=config)
            result = run_policy_on_batch(policy, mandates, config, seed)
            mandate_outcomes.extend(result.mandate_outcomes)
            attempt_outcomes.extend(result.attempt_outcomes)
        reports[policy_name] = compute_metrics(
            policy_name, mandate_outcomes, attempt_outcomes, config
        )
    return ScenarioResult(name=name, probes=probes, reports=reports)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sensitivity sweep")
    parser.add_argument("--seeds", type=int, default=10, help="Number of seeds per scenario")
    parser.add_argument("--n-mandates", type=int, default=200)
    parser.add_argument(
        "--policies", default="baseline,compliance_aware_baseline,adaptive,adaptive_hedged"
    )
    parser.add_argument(
        "--candidate", default="adaptive",
        help="Policy whose lift over baseline is summarised in the verdict",
    )
    args = parser.parse_args()

    base_config = load_config()
    scenarios = yaml.safe_load(SCENARIOS_PATH.read_text())["scenarios"]
    policy_names = [p.strip() for p in args.policies.split(",")]
    seeds = list(range(1, args.seeds + 1))

    print()
    print("=" * 94)
    print("  SENSITIVITY SWEEP -- does the result survive the assumption ranges?")
    print("=" * 94)
    print(f"  config frozen at   {base_config['meta']['frozen_commit_hash'][:12]}")
    print(f"  scenarios          {len(scenarios)}")
    print(f"  seeds per scenario {len(seeds)}   mandates per seed {args.n_mandates:,}")
    print()
    print("  All figures are SIMULATED-BATCH statistics, not measured against real transaction data.")
    print("=" * 94)
    print()

    header = (
        f"  {'scenario':32s} {'base':>7s} {'adapt':>7s} "
        f"{'rate lift':>10s} {'value lift':>11s} {'waste lift':>11s}"
    )
    print(header)
    print("  " + "-" * 90)

    results: list[ScenarioResult] = []
    for scenario in scenarios:
        result = run_scenario(
            name=scenario["name"],
            probes=scenario.get("probes", ""),
            config=build_scenario_config(base_config, scenario.get("overrides") or {}),
            policy_names=policy_names,
            seeds=seeds,
            n_mandates=args.n_mandates,
        )
        results.append(result)

        lift = result.lift("baseline", args.candidate)
        base_rate = result.reports["baseline"].recovery_rate_recoverable_only
        adapt_rate = result.reports[args.candidate].recovery_rate_recoverable_only
        print(
            f"  {result.name:32s} {base_rate:6.1%} {adapt_rate:6.1%} "
            f"{lift['recovery_rate_recoverable_only']:+9.1%} "
            f"{lift['recovered_value_inr']:+10.1%} "
            f"{lift['wasted_attempt_rate']:+10.1%}"
        )

    # ---- Verdict ----------------------------------------------------------------------------
    rate_lifts = [r.lift("baseline", args.candidate)["recovery_rate_recoverable_only"] for r in results]
    value_lifts = [r.lift("baseline", args.candidate)["recovered_value_inr"] for r in results]
    waste_lifts = [r.lift("baseline", args.candidate)["wasted_attempt_rate"] for r in results]

    positive_rate = sum(1 for x in rate_lifts if x > 0)
    positive_value = sum(1 for x in value_lifts if x > 0)
    improved_waste = sum(1 for x in waste_lifts if x < 0)  # negative == fewer wasted attempts

    def finite(values: list[float]) -> list[float]:
        """Relative lift is undefined where the baseline scored zero (0 -> n is an infinite
        increase). Those scenarios are excluded from range/median and counted separately rather
        than rendered as '+inf%', which is accurate but tells a reader nothing."""
        return [x for x in values if np.isfinite(x)]

    rate_lifts_f, value_lifts_f, waste_lifts_f = (
        finite(rate_lifts), finite(value_lifts), finite(waste_lifts)
    )
    undefined = len(waste_lifts) - len(waste_lifts_f)

    print()
    print("=" * 94)
    print("  VERDICT")
    print("=" * 94)
    print(f"  candidate policy                 {args.candidate}")
    print(f"  recovery-rate lift positive in   {positive_rate}/{len(results)} scenarios   "
          f"range {min(rate_lifts_f):+.1%} to {max(rate_lifts_f):+.1%}   median {np.median(rate_lifts_f):+.1%}")
    print(f"  value lift positive in           {positive_value}/{len(results)} scenarios   "
          f"range {min(value_lifts_f):+.1%} to {max(value_lifts_f):+.1%}   median {np.median(value_lifts_f):+.1%}")
    print(f"  wasted attempts IMPROVED in      {improved_waste}/{len(results)} scenarios   "
          f"range {min(waste_lifts_f):+.1%} to {max(waste_lifts_f):+.1%}   median {np.median(waste_lifts_f):+.1%}"
          + (f"   ({undefined} undefined: baseline had zero waste)" if undefined else ""))

    strongest = next((r for r in results if r.name == "baseline_strongest_spread"), None)
    if strongest is not None:
        lift = strongest.lift("baseline", args.candidate)
        print()
        print("  CONSERVATIVE HEADLINE -- against the strongest baseline we could construct:")
        print(f"    recovery-rate lift  {lift['recovery_rate_recoverable_only']:+.1%}")
        print(f"    value lift          {lift['recovered_value_inr']:+.1%}")
        print(f"    wasted-attempt lift {lift['wasted_attempt_rate']:+.1%}  (negative is better)")

    losing = [r.name for r, x in zip(results, rate_lifts) if x <= 0]
    if losing:
        print()
        print(f"  Scenarios where adaptive does NOT improve recovery rate: {', '.join(losing)}")
    print("=" * 94)
    print()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "sensitivity_summary.json"
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_frozen_commit_hash": base_config["meta"]["frozen_commit_hash"],
        "seeds": seeds,
        "n_mandates_per_seed": args.n_mandates,
        "data_source": "simulation",
        "scenarios": [
            {
                "name": r.name,
                "probes": r.probes,
                "reports": {k: vars(v) for k, v in r.reports.items()},
                "lift_candidate_vs_baseline": r.lift("baseline", args.candidate),
            }
            for r in results
        ],
    }, indent=2, default=str))
    print(f"  written to {out.relative_to(Path.cwd())}")
    print()


if __name__ == "__main__":
    main()
