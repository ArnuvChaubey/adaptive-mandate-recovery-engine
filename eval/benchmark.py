"""Measures decision throughput, so the number in the README is reproducible rather than asserted.

Until this module existed, `HANDOFF.md` carried a throughput figure described as "measured, not
estimated" with nothing in the repository to reproduce it. In a project whose entire argument is that
you should be able to re-run every number, an unreproducible number is worse than no number. This
closes that.

**What is being timed**, precisely, because "decisions per second" is meaningless without a boundary:

  - `policy.decide(state, config)` -- the full rule ladder
  - `evaluate_all(proposed, config)` -- every compliance invariant
  - the veto that turns a non-compliant retry into a blocked one

**What is NOT timed**, and would be dishonest to include:

  - mandate generation and balance-trajectory simulation (setup, not decision)
  - the audit-record write and the metrics pipeline (I/O and accounting)
  - anything the LLM touches -- narration and red-teaming are not in the decision path at all

The states are built once, up front, so the loop measures decision logic rather than object
construction. They deliberately span all six failure classes and straddle the OTP ceiling, so the
measurement covers every branch of the ladder rather than the cheapest one.

    python -m eval.benchmark
    python -m eval.benchmark --n 200000 --repeats 5
"""

import argparse
import platform
import random
import statistics
import sys
import time
from datetime import datetime, timedelta

from audit.decision_log_schema.records import DecisionType
from compliance.invariants.rules import (
    ProposedDecision,
    apply_compliance_veto,
    evaluate_all,
    rbi_category_for,
)
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.policy_interface.base import MandateView, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass

# Straddles the INR 15,000 no-OTP ceiling and the INR 1,00,000 higher ceiling (A6) so the escalation
# branch is exercised, not just the retry branch.
_AMOUNTS = [199.0, 1_499.0, 9_999.0, 14_999.0, 20_000.0, 41_000.0]
_TYPES = [AmountType.OTT_SUBSCRIPTION, AmountType.SIP_INVESTMENT, AmountType.EMI]
_CLASSES = list(FailureClass)


def build_states(n: int) -> list[PolicyState]:
    """Constructs n decision inputs covering every failure class and both sides of the ceiling.

    Built from the explicit cartesian product of (amount, type, failure class) rather than by
    indexing three lists with `i`. The first version did the latter, and
    `tests/test_benchmark_fidelity.py` caught why that was wrong: the three list lengths (6, 3, 6)
    share factors, so the combinations never varied independently -- the INR 41,000 EMI case always
    landed on the same failure class, which happened to be an unrecoverable one. Rule ADAPT-001
    short-circuits those before the ceiling check, so **the escalation branch was never executed and
    the benchmark was quietly measuring only the cheap paths.**

    A benchmark that misses a branch overstates throughput, which is the specific way a performance
    number becomes a lie without anyone editing it.
    """
    base = datetime(2026, 8, 15, 9, 0)
    combos = [
        (amount, amount_type, failure_class)
        for amount in _AMOUNTS
        for amount_type in _TYPES
        for failure_class in _CLASSES
    ]
    # Deterministically shuffled (fixed seed, so runs stay comparable) rather than left in product
    # order. In product order the axes vary at wildly different rates, so any prefix shorter than the
    # full 108 combinations is unrepresentative -- a short run would measure only small amounts, or
    # only the first few failure classes. Shuffling makes a prefix of any length a fair sample.
    random.Random(0).shuffle(combos)
    states = []
    for i in range(n):
        amount, amount_type, failure_class = combos[i % len(combos)]
        mandate = MandateView(
            mandate_id=f"bench_{i}",
            amount_inr=amount,
            amount_type=amount_type,
            created_at=base - timedelta(days=30),
            validity_days=365,
        )
        states.append(PolicyState(
            mandate=mandate,
            failure_class=failure_class,
            attempt_number=(i % 3) + 1,
            failed_at=base + timedelta(hours=i % 24),
            consecutive_failures=(i % 3) + 1,
        ))
    return states


def decide_and_check(policy, state: PolicyState, config: dict) -> DecisionType:
    """One complete decision: the rule ladder, every invariant, and the veto.

    Mirrors exactly what `eval/harness.py` does per attempt, minus the audit write.
    """
    decision = policy.decide(state, config)
    proposed = ProposedDecision(
        mandate_id=state.mandate.mandate_id,
        amount_inr=state.mandate.amount_inr,
        scheduled_retry_at=decision.scheduled_retry_at,
        notification_sent_at=decision.notification_to_send_at,
        amount_category=rbi_category_for(state.mandate.amount_type.value),
        is_new_notification=decision.notification_to_send_at is not None,
    )
    checks = evaluate_all(proposed, config)
    return apply_compliance_veto(decision.decision_type, checks)


def run(n: int, repeats: int, warmup: int) -> dict:
    config = load_config()
    policy = AdaptivePolicy()
    states = build_states(n)

    # Warm-up: let import-time lazies and branch prediction settle. Not counted.
    for state in states[:warmup]:
        decide_and_check(policy, state, config)

    rates = []
    for _ in range(repeats):
        start = time.perf_counter()
        for state in states:
            decide_and_check(policy, state, config)
        elapsed = time.perf_counter() - start
        rates.append(n / elapsed)

    return {
        "n_per_repeat": n,
        "repeats": repeats,
        "rates": rates,
        "median_per_sec": statistics.median(rates),
        "min_per_sec": min(rates),
        "max_per_sec": max(rates),
        "us_per_decision": 1_000_000 / statistics.median(rates),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure decision throughput")
    parser.add_argument("--n", type=int, default=100_000, help="decisions per repeat")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1_000)
    args = parser.parse_args()

    result = run(args.n, args.repeats, args.warmup)

    print()
    print("=" * 78)
    print("  DECISION THROUGHPUT -- single core, unoptimised, compliance checks included")
    print("=" * 78)
    print(f"  machine                {platform.processor() or platform.machine()}")
    print(f"  python                 {sys.version.split()[0]} ({platform.python_implementation()})")
    print(f"  decisions per repeat   {result['n_per_repeat']:,}")
    print(f"  repeats                {result['repeats']}")
    print()
    print(f"  median                 {result['median_per_sec']:,.0f} decisions/sec")
    print(f"  range                  {result['min_per_sec']:,.0f} - {result['max_per_sec']:,.0f}")
    print(f"  per decision           {result['us_per_decision']:.2f} microseconds")
    print()
    print("  Timed: the rule ladder + every compliance invariant + the veto.")
    print("  NOT timed: mandate generation, balance simulation, audit writes, metrics.")
    print()
    print("  Quote the MEDIAN, and quote it with the machine. A throughput number without")
    print("  the hardware it was measured on is not a reproducible claim.")
    print("=" * 78)
    print()


if __name__ == "__main__":
    main()
