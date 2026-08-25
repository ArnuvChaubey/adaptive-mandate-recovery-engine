"""The single reproducibility entrypoint.

No number appears in the README, the deck, or the pitch video that did not come out of this command.

    python -m eval.run_eval --policies baseline
    python -m eval.run_eval --policies baseline,adaptive --seeds config/seeds.txt
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from eval.harness import run_policy_on_batch
from eval.metrics.definitions import MetricsReport, compute_metrics, recovery_lift
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.baseline_policy.policy import BaselinePolicy
from policies.compliance_aware_baseline.policy import ComplianceAwareBaselinePolicy
from policies.policy_interface.base import Policy
from simulator.batch import generate_mandates
from simulator.config_loader import load_config

REPORTS_DIR = Path(__file__).parent / "reports"

AVAILABLE_POLICIES: dict[str, type[Policy]] = {
    "baseline": BaselinePolicy,
    "compliance_aware_baseline": ComplianceAwareBaselinePolicy,  # ablation, see that module's docstring
    "adaptive": AdaptivePolicy,
    # "external_engine_stub" is intentionally not registered -- see policies/external_policy_stub/.
}


def load_seeds(path: Path) -> list[int]:
    seeds = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            seeds.append(int(line))
    return seeds


def format_report(report: MetricsReport) -> str:
    iqr = (
        f"{report.iqr_days_to_recovery[0]:.1f}-{report.iqr_days_to_recovery[1]:.1f}"
        if report.iqr_days_to_recovery
        else "n/a"
    )
    median = (
        f"{report.median_days_to_recovery:.1f}"
        if report.median_days_to_recovery is not None
        else "n/a"
    )
    return "\n".join([
        f"  policy                        {report.policy_name}",
        f"  mandates                      {report.n_mandates:,}",
        f"  recovery rate (recoverable)   {report.recovery_rate_recoverable_only:.1%}",
        f"  recovery rate (all mandates)  {report.recovery_rate_all:.1%}",
        f"  value recovered               INR {report.recovered_value_inr:,.2f}"
        f"  of INR {report.total_value_inr:,.2f}",
        f"  attempts made                 {report.total_attempts:,}",
        f"  wasted attempts               {report.wasted_attempts:,} ({report.wasted_attempt_rate:.1%})",
        f"  days to recovery              median {median}, IQR {iqr}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mandate-recovery evaluation harness")
    parser.add_argument("--config", default=None, help="Path to sim_params.yaml")
    parser.add_argument("--seeds", default=None, help="Path to a seed list file")
    parser.add_argument("--seed", type=int, default=None, help="Single seed (overrides --seeds)")
    parser.add_argument("--policies", default="baseline", help="Comma-separated policy names")
    parser.add_argument("--n-mandates", type=int, default=500)
    parser.add_argument("--write-log", action="store_true", help="Write the decision log to JSONL")
    args = parser.parse_args()

    config = load_config(args.config) if args.config else load_config()

    if args.seed is not None:
        seeds = [args.seed]
    elif args.seeds:
        seeds = load_seeds(Path(args.seeds))
    else:
        seeds = [1]

    policy_names = [p.strip() for p in args.policies.split(",")]
    for name in policy_names:
        if name not in AVAILABLE_POLICIES:
            raise SystemExit(
                f"Unknown policy '{name}'. Available: {', '.join(AVAILABLE_POLICIES)}"
            )

    print()
    print("=" * 72)
    print("  ADAPTIVE MANDATE RECOVERY ENGINE -- evaluation harness")
    print("=" * 72)
    print(f"  config frozen at commit  {config['meta']['frozen_commit_hash'][:12]}")
    print(f"  seeds                    {seeds if len(seeds) <= 8 else f'{len(seeds)} seeds'}")
    print(f"  mandates per seed        {args.n_mandates:,}")
    print()
    print("  NOTE: every figure below is a SIMULATED-BATCH statistic computed from the frozen")
    print("  config above. It is not measured against real transaction data. See README.")
    print("=" * 72)

    reports: dict[str, MetricsReport] = {}
    for name in policy_names:
        policy = AVAILABLE_POLICIES[name]()
        all_mandate_outcomes, all_attempt_outcomes = [], []
        last_log = None
        total_blocked = 0  # aggregated across every seed, not just the last one

        for seed in seeds:
            mandates = generate_mandates(n=args.n_mandates, seed=seed, config=config)
            result = run_policy_on_batch(policy, mandates, config, seed)
            all_mandate_outcomes.extend(result.mandate_outcomes)
            all_attempt_outcomes.extend(result.attempt_outcomes)
            total_blocked += len(result.decision_log.compliance_failures())
            last_log = result.decision_log

        report = compute_metrics(name, all_mandate_outcomes, all_attempt_outcomes, config)
        reports[name] = report

        print()
        print(format_report(report))

        pct = total_blocked / len(all_mandate_outcomes) if all_mandate_outcomes else 0.0
        print(
            f"  non-compliant proposals       {total_blocked:,} blocked "
            f"({pct:.1%} of mandates, all seeds)"
        )

        if last_log is not None:
            if args.write_log:
                out = REPORTS_DIR / f"decision_log_{name}.jsonl"
                last_log.write_jsonl(out)
                print(f"  decision log written          {out.relative_to(Path.cwd())}")

    if len(policy_names) > 1 and "baseline" in reports:
        print()
        print("-" * 72)
        print("  RECOVERY LIFT")
        print("-" * 72)

        # Decomposition, when the ablation was run: separates lift attributable to compliance
        # awareness from lift attributable to retry timing. See
        # policies/compliance_aware_baseline/ for why this decomposition is not optional.
        comparisons: list[tuple[str, str, str]] = []
        if "compliance_aware_baseline" in reports and "adaptive" in reports:
            comparisons = [
                ("baseline", "compliance_aware_baseline", "compliance awareness alone"),
                ("compliance_aware_baseline", "adaptive", "retry timing alone"),
                ("baseline", "adaptive", "TOTAL"),
            ]
        else:
            comparisons = [
                ("baseline", name, "vs baseline") for name in reports if name != "baseline"
            ]

        for base_name, cand_name, label in comparisons:
            print(f"\n  {cand_name} vs {base_name}  --  {label}:")
            for metric, value in recovery_lift(reports[base_name], reports[cand_name]).items():
                print(f"    {metric:32s} {value:+.1%}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_frozen_commit_hash": config["meta"]["frozen_commit_hash"],
        "seeds": seeds,
        "n_mandates_per_seed": args.n_mandates,
        "data_source": "simulation",
        "reports": {
            name: {
                k: v for k, v in vars(r).items()
            }
            for name, r in reports.items()
        },
    }
    (REPORTS_DIR / "latest_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print()
    print(f"  summary written to {(REPORTS_DIR / 'latest_summary.json').relative_to(Path.cwd())}")
    print()


if __name__ == "__main__":
    main()
