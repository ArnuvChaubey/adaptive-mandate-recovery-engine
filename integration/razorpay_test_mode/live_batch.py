"""Runs the real policy engine against real Razorpay test-mode entities.

**What this proves, and what it does not.**

Proves: the same policy engine, the same compliance invariants, and the same audit schema operate on
entities fetched from Razorpay's live test-mode API, not just on simulator output. The policy never
knew which it was reading. Decisions are written with `source: live_test_mode` so no reader can
mistake them for simulated ones.

Does NOT prove: any recovery-rate or lift claim. This is a handful of real entities, not a
statistically powered sample (A30), and the batch is deliberately not counted in any headline number.

**Why the batch isn't 15-20 completed payments.** Completing a payment requires Razorpay's hosted
checkout, which needs a human and actively resists automation (see docs/build_log.md entry 4).
Razorpay's server-to-server API, which would allow programmatic payment creation, requires contacting
their support team to enable and is not available on a fresh test account. There is no test-mode
payment-simulation endpoint. So the scripted portion covers everything that genuinely is scriptable
-- creation, retrieval, decline-code mapping, policy decision, compliance check, audit write -- and
the payment step is exercised separately and manually (see create_test_payment_link.py).

    python -m integration.razorpay_test_mode.live_batch --count 15
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from audit.decision_log_schema.records import (
    DecisionLog,
    DecisionRecord,
    Source,
)
from compliance.invariants.rules import ProposedDecision, evaluate_all
from integration.razorpay_test_mode.client import get_client
from integration.razorpay_test_mode.failure_mapping import (
    TEST_CARDS_BY_ERROR_REASON,
    map_error_reason,
)
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.policy_interface.base import MandateView, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass

OUT_PATH = Path(__file__).parent.parent.parent / "eval" / "reports" / "live_test_mode_decisions.jsonl"

# Amounts chosen to straddle the INR 15,000 no-OTP ceiling (A6) so the live batch exercises both the
# retry path and the compliant-escalation path against real entities, not just the easy one.
AMOUNTS_INR = [199, 499, 1_499, 4_999, 9_999, 14_999, 18_500, 26_000, 41_000]


# Razorpay rate-limits test-mode writes; a tight loop trips "Too many requests" within a handful of
# calls. Real payment integrations have to pace themselves and back off, so the batch does too --
# this is part of what "the integration works" means, not an inconvenience around it.
INTER_CALL_DELAY_SECONDS = 1.5
MAX_BACKOFF_RETRIES = 4


def _with_backoff(operation, description: str):
    """Runs a Razorpay API call, backing off on rate limits.

    Returns None if the call cannot be completed, so a rate limit degrades the batch rather than
    aborting it and discarding the decisions already recorded.
    """
    delay = 2.0
    for attempt in range(1, MAX_BACKOFF_RETRIES + 1):
        try:
            return operation()
        except Exception as exc:
            if "too many requests" not in str(exc).lower():
                print(f"      ! {description} failed: {exc}")
                return None
            if attempt == MAX_BACKOFF_RETRIES:
                print(f"      ! {description} rate-limited after {attempt} attempts, skipping")
                return None
            print(f"      . rate limited, backing off {delay:.0f}s "
                  f"(attempt {attempt}/{MAX_BACKOFF_RETRIES})")
            time.sleep(delay)
            delay *= 2
    return None


def _amount_type_for(amount_inr: float) -> AmountType:
    if amount_inr <= 999:
        return AmountType.OTT_SUBSCRIPTION
    if amount_inr <= 25_000:
        return AmountType.SIP_INVESTMENT
    return AmountType.EMI


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the policy against real Razorpay entities")
    parser.add_argument("--count", type=int, default=9)
    args = parser.parse_args()

    load_dotenv()
    client = get_client()
    config = load_config()
    policy = AdaptivePolicy()
    log = DecisionLog()

    print()
    print("=" * 90)
    print("  LIVE TEST-MODE BATCH -- real Razorpay API, real policy engine")
    print("=" * 90)
    print("  Every entity below is created and re-fetched through Razorpay's test-mode API.")
    print("  Policy decisions are tagged source=live_test_mode and are NOT counted in any")
    print("  recovery-rate or lift figure. See A30.")
    print("=" * 90)
    print()

    error_reasons = list(TEST_CARDS_BY_ERROR_REASON.keys())
    created = 0

    for i in range(args.count):
        amount_inr = AMOUNTS_INR[i % len(AMOUNTS_INR)]

        if i > 0:
            time.sleep(INTER_CALL_DELAY_SECONDS)

        # 1. Real API write.
        link = _with_backoff(
            lambda: client.payment_link.create({
                "amount": int(amount_inr * 100),
                "currency": "INR",
                "description": f"Live batch case {i + 1} -- integration proof, not a real product",
                "customer": {
                    "name": f"Test Customer {i + 1}",
                    "email": f"test.customer.{i + 1}@example.com",
                    "contact": "+919123456789",
                },
                "notify": {"sms": False, "email": False},
                "notes": {"project": "adaptive-mandate-recovery-engine", "purpose": "m6-live-batch"},
            }),
            f"create payment link {i + 1}",
        )
        if link is None:
            continue

        # 2. Real API read -- proves round-trip, not just fire-and-forget.
        fetched = _with_backoff(
            lambda: client.payment_link.fetch(link["id"]), f"fetch payment link {i + 1}"
        )
        if fetched is None:
            continue
        created += 1

        # 3. Map a documented Razorpay decline code onto the failure taxonomy. Unpaid links carry no
        #    decline code of their own, so each case is assigned one of Razorpay's published
        #    error_reason values in rotation -- the mapping under test is the taxonomy join, and it
        #    is exercised against the real code strings rather than invented ones.
        error_reason = error_reasons[i % len(error_reasons)]
        failure_class = map_error_reason(error_reason)

        if failure_class is None:
            print(f"  [{i + 1:2d}] {fetched['id']:22s} INR {amount_inr:>9,.2f}  "
                  f"{error_reason:34s} -> not recoverable by retry, no policy decision")
            continue

        # 4. Real entity -> policy input. The policy cannot tell this apart from simulator output,
        #    which is the point of the MandateView boundary.
        mandate = MandateView(
            mandate_id=fetched["id"],
            amount_inr=amount_inr,
            amount_type=_amount_type_for(amount_inr),
            created_at=datetime.fromtimestamp(fetched["created_at"], tz=timezone.utc).replace(tzinfo=None),
            validity_days=365,
        )
        state = PolicyState(
            mandate=mandate,
            failure_class=failure_class,
            attempt_number=1,
            failed_at=datetime.now(),
            consecutive_failures=1,
        )
        decision = policy.decide(state, config)

        # 5. Same compliance invariants as the simulated path.
        checks = evaluate_all(
            ProposedDecision(
                mandate_id=mandate.mandate_id,
                amount_inr=amount_inr,
                scheduled_retry_at=decision.scheduled_retry_at,
                notification_sent_at=decision.notification_to_send_at,
            ),
            config,
        )

        # 6. Same audit schema, different source tag.
        log.append(DecisionRecord(
            decision_id=f"live_{fetched['id']}",
            mandate_id=fetched["id"],
            policy_name=policy.name,
            decision_type=decision.decision_type,
            rule_id=decision.rule_id,
            rule_description=decision.rule_description,
            failure_class=failure_class.value,
            attempt_number=1,
            decided_at=datetime.now(),
            source=Source.LIVE_TEST_MODE,
            scheduled_retry_at=decision.scheduled_retry_at,
            escalation_action=decision.escalation_action,
            compliance_checks=checks,
            amount_inr=amount_inr,
            metadata={
                "razorpay_error_reason": error_reason,
                "razorpay_test_card": TEST_CARDS_BY_ERROR_REASON[error_reason],
                "razorpay_status": fetched.get("status"),
                "short_url": fetched.get("short_url"),
            },
        ))

        print(f"  [{i + 1:2d}] {fetched['id']:22s} INR {amount_inr:>9,.2f}  "
              f"{error_reason:34s} -> {decision.decision_type.value:28s} {decision.rule_id}")

    log.write_jsonl(OUT_PATH)

    escalations = sum(
        1 for r in log if r.escalation_action is not None
    )
    print()
    print("-" * 90)
    print(f"  entities created + re-fetched via real API : {created}")
    print(f"  policy decisions recorded                  : {len(log)}")
    print(f"  compliant escalations                      : {escalations}")
    print(f"  compliance violations                      : {len(log.compliance_failures())}")
    print(f"  written to                                 : {OUT_PATH.relative_to(Path.cwd())}")
    print("-" * 90)
    print()


if __name__ == "__main__":
    main()
