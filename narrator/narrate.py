"""Narrate decisions from a run.

    python -m narrator.narrate --limit 6

Runs the policy, takes a spread of decision records, and prints the narration for each. Works with
or without an ANTHROPIC_API_KEY -- without one it uses the deterministic templates and says so.
"""

import argparse

from dotenv import load_dotenv

from audit.decision_log_schema.records import DecisionType
from eval.harness import run_policy_on_batch
from narrator.llm_explainer.explainer import narrate
from policies.adaptive_policy.policy import AdaptivePolicy
from simulator.batch import generate_mandates
from simulator.config_loader import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Narrate decision-log records")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--n-mandates", type=int, default=200)
    args = parser.parse_args()

    load_dotenv()  # ANTHROPIC_API_KEY, if configured; absence is a supported path, not an error

    config = load_config()
    mandates = generate_mandates(n=args.n_mandates, seed=args.seed, config=config)
    result = run_policy_on_batch(AdaptivePolicy(), mandates, config, args.seed)

    # A spread across decision types, not the first N -- otherwise every example is the same rule.
    by_type: dict[DecisionType, list] = {}
    for record in result.decision_log:
        by_type.setdefault(record.decision_type, []).append(record)

    selected = []
    while len(selected) < args.limit and any(by_type.values()):
        for records in by_type.values():
            if records and len(selected) < args.limit:
                selected.append(records.pop(0))

    print()
    print("=" * 88)
    print("  DECISION NARRATION")
    print("=" * 88)
    print("  The narrator reads the audit log AFTER decisions are made. It never influences one.")
    print("  Ungrounded LLM output is discarded in favour of the deterministic template.")
    print("=" * 88)

    for i, record in enumerate(selected, 1):
        n = narrate(record)
        print()
        print(f"  [{i}] {record.decision_type.value}   rule {record.rule_id}   "
              f"INR {record.amount_inr:,.2f}   ({record.failure_class})")
        print(f"      narration source : {n.source}")
        if n.validation is not None and not n.validation.passed:
            print(f"      validation       : REJECTED -- {n.validation.summary}")
        print(f"      influenced decision: {n.influenced_decision}")
        print()
        print(f"      INTERNAL: {n.internal_explanation}")
        print(f"      CUSTOMER: {n.customer_message or '(no customer contact appropriate)'}")

    print()
    print("=" * 88)
    print()


if __name__ == "__main__":
    main()
