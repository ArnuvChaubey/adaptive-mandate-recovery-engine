"""Adversarial scenario generation: Claude attacks this project's own results.

Every other use of an LLM in a recovery system points the same direction -- the model advocates for
an action, and a human hopes it was right. This points the other way. Claude is given the assumption
table and the frozen config and asked to find parameterisations where the adaptive policy *loses*.
It proposes; the harness disposes.

**Why this is a defensible use of a model and the decision loop is not.** Generating diverse,
plausible, adversarial hypotheses is something language models are genuinely good at and deterministic
code is bad at -- it requires reading prose assumptions and reasoning about which combinations would
be hostile. But nothing the model says is trusted:

  1. every proposed scenario is mechanically validated against the schema and the ranges already
     declared in sim_params.yaml -- a path that doesn't exist or a value outside its declared range
     is rejected before it can run;
  2. surviving scenarios are executed by the same sweep machinery as the hand-written ones;
  3. the verdict comes from the metrics, not from the model.

So the model can be wrong, lazy, or hallucinating and the worst case is a wasted scenario -- never a
false result. An attack that succeeds is reported as a real weakness, because a red team that never
lands a hit is decoration.

    python -m eval.redteam --count 8
"""

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from dotenv import load_dotenv

from eval.run_eval import REPORTS_DIR
from eval.sensitivity import ScenarioResult, apply_override, build_scenario_config, run_scenario
from simulator.config_loader import load_config

MODEL = "claude-opus-5"
ASSUMPTIONS_PATH = Path(__file__).parent.parent / "assumptions.md"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sim_params.yaml"
OUT_PATH = REPORTS_DIR / "redteam_summary.json"

SYSTEM_PROMPT = """You are a skeptical staff engineer reviewing a payment-recovery evaluation \
harness. Your job is to BREAK its central claim, not to validate it.

The claim: a context-aware adaptive retry policy recovers more failed payment mandates than a fixed \
retry schedule. The authors believe this holds across every parameterisation they have tested. You \
suspect they have not tested the hostile ones.

You will be given their assumption table and their frozen simulator config. Produce scenarios -- \
specific parameter settings -- under which the adaptive policy would plausibly LOSE to the fixed \
baseline, or where its advantage would collapse.

Rules you must follow, because scenarios that break them are discarded automatically:

1. Only use override paths that exist in the config you are shown. Use exact dotted paths.
2. Where the config declares a `range: [lo, hi]` for a value, your scenario must stay INSIDE that \
range. Moving outside a declared range is moving the goalposts, not stress-testing. Collapse a range \
to a single point by writing [x, x].
3. Every scenario needs a one-sentence plausibility argument grounded in how payments actually work \
in India. "Set everything to the worst value" is not an attack, it is a tantrum.
4. Prefer COMBINATIONS. The authors swept parameters one at a time. Interaction effects are where \
their blind spot most likely is.
5. Think about mechanism. What does the adaptive policy actually rely on? Where would that reliance \
become a liability?

Return ONLY valid YAML, no prose outside it, in exactly this shape:

scenarios:
  - name: snake_case_name
    probes: "which assumption(s) this attacks and why the policy should struggle"
    plausibility: "why a payments engineer would accept this as a real possibility"
    overrides:
      some.dotted.path: value
"""


@dataclass
class ProposedScenario:
    name: str
    probes: str
    plausibility: str
    overrides: dict[str, Any]
    rejected_reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.rejected_reason is None


@dataclass
class RedTeamOutcome:
    scenario: ProposedScenario
    result: ScenarioResult
    rate_lift: float
    value_lift: float
    waste_lift: float

    @property
    def attack_landed(self) -> bool:
        """The policy lost on a headline metric under this scenario."""
        return self.rate_lift <= 0 or self.value_lift <= 0


def _declared_ranges(config: dict, prefix: str = "") -> dict[str, list]:
    """Every `range: [lo, hi]` in the frozen config, keyed by its dotted path."""
    found: dict[str, list] = {}

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if key == "range" and isinstance(value, list) and len(value) == 2:
                found[child] = value
            walk(value, child)

    walk(config, prefix)
    return found


def validate(scenario: ProposedScenario, config: dict) -> ProposedScenario:
    """Mechanically checks a proposed scenario. Nothing the model claims is taken on trust."""
    ranges = _declared_ranges(config)

    for path, value in scenario.overrides.items():
        # Path must exist. apply_override raises loudly rather than silently creating keys, which
        # would let a typo produce a scenario that tests nothing while appearing to pass.
        try:
            apply_override(json.loads(json.dumps(config)), path, value)
        except KeyError as exc:
            scenario.rejected_reason = f"invalid path: {exc}"
            return scenario

        if path in ranges and isinstance(value, list) and len(value) == 2:
            lo, hi = ranges[path]
            try:
                if float(value[0]) < float(lo) - 1e-9 or float(value[1]) > float(hi) + 1e-9:
                    scenario.rejected_reason = (
                        f"{path}={value} escapes the declared range {[lo, hi]} -- moving the "
                        "goalposts, not stress-testing"
                    )
                    return scenario
            except (TypeError, ValueError):
                pass

        if path.endswith("failure_class_mix.weights") and isinstance(value, dict):
            total = sum(float(v) for v in value.values())
            if not 0.97 <= total <= 1.03:
                scenario.rejected_reason = f"failure-class weights sum to {total:.2f}, not 1.0"
                return scenario

    if not scenario.overrides:
        scenario.rejected_reason = "no overrides -- not a scenario"
    if not scenario.plausibility.strip():
        scenario.rejected_reason = "no plausibility argument given"
    return scenario


def _extract_yaml(text: str) -> str:
    """Pulls YAML out of a model response, tolerating an unterminated code fence.

    The first live run hit exactly that: the response was truncated at max_tokens, so the closing
    fence never arrived and a naive paired-fence regex returned the raw text including ```yaml,
    which is not parseable. Same failure family as the narrator truncation -- the guard has to cope
    with output that stops early, not just output that is wrong.
    """
    closed = re.search(r"```(?:yaml)?\s*(.+?)```", text, re.S)
    if closed:
        return closed.group(1).strip()
    unterminated = re.search(r"```(?:yaml)?\s*(.+)", text, re.S)
    if unterminated:
        return unterminated.group(1).strip()
    return text.strip()


def generate(config: dict, count: int, client=None) -> list[ProposedScenario]:
    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    # The existing hand-written scenarios are included as worked examples. The first live run had two
    # proposals rejected for trying to index into a list (`...types[0].weight_range`), which the
    # override mechanism does not support -- showing the working pattern is cheaper than teaching a
    # path grammar in prose, and it also signals which attacks have already been tried.
    examples = (Path(__file__).parent.parent / "config" / "scenarios.yaml").read_text()

    prompt = (
        f"Their assumption table:\n\n{ASSUMPTIONS_PATH.read_text()[:14000]}\n\n"
        f"Their frozen simulator config:\n\n{CONFIG_PATH.read_text()}\n\n"
        f"Scenarios they have ALREADY tested -- use these as worked examples of valid override "
        f"syntax, and do not simply repeat them:\n\n{examples}\n\n"
        f"Note the syntax for list-valued config: override the whole list, as "
        f"`income_event_population_mixture.types` does. Indexing into a list "
        f"(`types[0].weight_range`) is not supported and will be rejected.\n\n"
        f"Produce {count} scenarios designed to make the adaptive policy lose. Their existing "
        f"scenarios all leave the policy ahead by at least +10% on recovery rate; find something "
        f"they missed."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        # Genuinely hard reasoning: it has to understand the policy's mechanism from prose and find
        # hostile interactions. Unlike narration, this is where effort actually buys something.
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")

    if getattr(response, "stop_reason", None) == "max_tokens":
        print("  ! response truncated at max_tokens -- parsing what arrived, some scenarios lost")

    try:
        parsed = yaml.safe_load(_extract_yaml(text)) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"model returned unparseable YAML: {exc}")

    return [
        ProposedScenario(
            name=str(s.get("name", f"unnamed_{i}")),
            probes=str(s.get("probes", "")),
            plausibility=str(s.get("plausibility", "")),
            overrides=s.get("overrides") or {},
        )
        for i, s in enumerate(parsed.get("scenarios", []))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Let Claude attack the project's own results")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--n-mandates", type=int, default=200)
    parser.add_argument("--candidate", default="adaptive")
    args = parser.parse_args()

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set -- red-teaming needs the model")

    config = load_config()
    seeds = list(range(1, args.seeds + 1))

    print()
    print("=" * 94)
    print("  ADVERSARIAL RED TEAM -- the model attacks, the harness adjudicates")
    print("=" * 94)
    print("  Claude proposes parameterisations designed to make the adaptive policy lose.")
    print("  Every proposal is validated against the declared ranges before it is allowed to run,")
    print("  and the verdict comes from the metrics, not from the model.")
    print("=" * 94)
    print()

    proposals = [validate(s, config) for s in generate(config, args.count)]
    valid = [s for s in proposals if s.valid]
    rejected = [s for s in proposals if not s.valid]

    print(f"  proposed {len(proposals)}   accepted {len(valid)}   rejected {len(rejected)}")
    for s in rejected:
        print(f"    REJECTED  {s.name}: {s.rejected_reason}")
    print()

    if not valid:
        raise SystemExit("no valid scenarios survived validation")

    header = (
        f"  {'attack':34s} {'base':>7s} {'adapt':>7s} {'rate':>9s} {'value':>9s}  verdict"
    )
    print(header)
    print("  " + "-" * 90)

    outcomes: list[RedTeamOutcome] = []
    for s in valid:
        result = run_scenario(
            name=s.name,
            probes=s.probes,
            config=build_scenario_config(config, s.overrides),
            policy_names=["baseline", args.candidate],
            seeds=seeds,
            n_mandates=args.n_mandates,
        )
        lift = result.lift("baseline", args.candidate)
        outcome = RedTeamOutcome(
            scenario=s,
            result=result,
            rate_lift=lift["recovery_rate_recoverable_only"],
            value_lift=lift["recovered_value_inr"],
            waste_lift=lift["wasted_attempt_rate"],
        )
        outcomes.append(outcome)

        base = result.reports["baseline"].recovery_rate_recoverable_only
        cand = result.reports[args.candidate].recovery_rate_recoverable_only
        verdict = "*** ATTACK LANDED ***" if outcome.attack_landed else "held"
        print(f"  {s.name:34s} {base:6.1%} {cand:6.1%} "
              f"{outcome.rate_lift:+8.1%} {outcome.value_lift:+8.1%}  {verdict}")

    landed = [o for o in outcomes if o.attack_landed]
    rate_lifts = [o.rate_lift for o in outcomes]

    print()
    print("=" * 94)
    print("  VERDICT")
    print("=" * 94)
    print(f"  attacks that landed   {len(landed)}/{len(outcomes)}")
    print(f"  weakest rate lift     {min(rate_lifts):+.1%}  ({min(outcomes, key=lambda o: o.rate_lift).scenario.name})")
    print(f"  median rate lift      {np.median(rate_lifts):+.1%}")
    if landed:
        print()
        print("  The policy lost under these conditions:")
        for o in landed:
            print(f"    - {o.scenario.name}: {o.scenario.probes}")
            print(f"      plausibility: {o.scenario.plausibility}")
    else:
        print()
        print("  No attack landed. That is a weaker statement than it looks: it means the model")
        print("  could not find a losing parameterisation inside the declared ranges, not that one")
        print("  does not exist outside them.")
    print("=" * 94)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "config_frozen_commit_hash": config["meta"]["frozen_commit_hash"],
        "candidate": args.candidate,
        "proposed": len(proposals),
        "rejected": [{"name": s.name, "reason": s.rejected_reason} for s in rejected],
        "attacks": [
            {
                "name": o.scenario.name,
                "probes": o.scenario.probes,
                "plausibility": o.scenario.plausibility,
                "overrides": o.scenario.overrides,
                "rate_lift": o.rate_lift,
                "value_lift": o.value_lift,
                "waste_lift": o.waste_lift,
                "attack_landed": o.attack_landed,
            }
            for o in outcomes
        ],
    }, indent=2, default=str))
    print(f"\n  written to {OUT_PATH.relative_to(Path.cwd())}\n")


if __name__ == "__main__":
    main()
