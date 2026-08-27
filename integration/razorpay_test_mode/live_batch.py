"""Runs the real policy engine against real Razorpay test-mode entities.

**What this proves, and what it does not.**

Proves: the same policy engine, the same compliance invariants, and the same audit schema operate on
entities fetched from Razorpay's live test-mode API, not just on simulator output. The policy never
knew which it was reading. Decisions are written with `source: live_test_mode` so no reader can
mistake them for simulated ones. As of entry 25, a compliant RETRY_SCHEDULED decision also **fires a
real action**, not just a recorded intent -- see `_fire_retry_action` below.

Does NOT prove: any recovery-rate or lift claim. This is a handful of real entities, not a
statistically powered sample (A30), and the batch is deliberately not counted in any headline number.
It also does not prove the retry *succeeds* -- see the boundary below.

**Why the batch isn't 15-20 completed payments.** Completing a payment requires Razorpay's hosted
checkout, which needs a human and actively resists automation (see docs/build_log.md entry 4).
Razorpay's server-to-server API, which would allow programmatic payment creation, requires contacting
their support team to enable and is not available on a fresh test account. There is no test-mode
payment-simulation endpoint. So the scripted portion covers everything that genuinely is scriptable
-- retrieval, decline-code mapping, policy decision, compliance check, **compliance veto, firing the
retry as a real new entity**, audit write -- and completing a checkout is exercised separately and
manually (see create_test_payment_link.py). The line is drawn in exactly the same place entry 4 already
drew it: read + decide + act is scriptable, a human clicking through a hosted payment page is not, and
scripting around that boundary was already rejected once as wrong, not merely untried.

**It reads existing entities rather than creating them.** A recovery system reacts to a payment that
already failed; it does not create its own subject. Earlier versions created a fresh Payment Link per
case, which was both the less faithful model and -- once test mode's lifetime cap of 30 Payment Links
was reached (entry 25) -- not re-runnable at all. Reading makes the batch idempotent: run it as many
times as you like, on whatever the account actually holds.

**What "firing a retry" means here, precisely.** The retry action creates a real Razorpay **Order**:
the payment-intent primitive, carrying the amount, a merchant `receipt` naming the original mandate and
attempt number, and `notes` with the rule id that decided it plus the `scheduled_retry_at` the policy
computed. The order is re-fetched to confirm it exists, and its id goes into the decision record, so
the action is independently verifiable against Razorpay's API rather than merely asserted in a log.

Two boundaries, stated rather than blurred: the order is created *immediately* rather than at
`scheduled_retry_at` (a script can't idle for a T+7 cadence), which is recorded in the record's own
metadata; and creating a payment intent is not the same as collecting money -- this proves the decision
reaches the API as a real action, not that the retry succeeds.

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
    DecisionType,
    Source,
)
from compliance.invariants.rules import ProposedDecision, apply_compliance_veto, evaluate_all
from integration.razorpay_test_mode.client import get_client
from integration.razorpay_test_mode.failure_mapping import (
    TEST_CARDS_BY_ERROR_REASON,
    map_error_reason,
)
from policies.adaptive_policy.policy import AdaptivePolicy
from policies.policy_interface.base import Decision, MandateView, PolicyState
from simulator.config_loader import load_config
from simulator.mandate import AmountType, FailureClass

OUT_PATH = Path(__file__).parent.parent.parent / "eval" / "reports" / "live_test_mode_decisions.jsonl"

# Razorpay rate-limits test-mode writes; a tight loop trips "Too many requests" within a handful of
# calls. Real payment integrations have to pace themselves and back off, so the batch does too --
# this is part of what "the integration works" means, not an inconvenience around it.
#
# Raised from 1.5s to 4.0s in entry 25: firing real retry actions added write volume per case (fetch
# the original, then create + fetch the retry order), and the old pacing -- calibrated when a case was
# read-only after creation -- started tripping the limiter partway through. The constant was tuned to
# the old call volume and had to move with it.
INTER_CALL_DELAY_SECONDS = 4.0
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


def _fire_retry_action(
    client, with_backoff, case_index: int, original_link: dict, decision: Decision, attempt_number: int,
) -> dict | None:
    """Actually executes a compliant retry decision as a real Razorpay API write.

    This is the piece HANDOFF.md flagged as missing: until entry 25, every decision in this batch was
    *recorded* but nothing downstream of a RETRY_SCHEDULED decision ever caused a new real entity to
    exist. Only called after `apply_compliance_veto` -- a decision that arrives here has already
    passed compliance, by construction, not by re-checking.

    **Why an Order and not another Payment Link.** The first version created a Payment Link, which
    worked and is verifiable (four fired that way, see entry 25). It was replaced for two reasons, in
    this order of importance: an Order is the *payment-intent* primitive -- "collect this amount, this
    is attempt N, here's the merchant reference" -- while a Payment Link is that plus a hosted page and
    a customer-facing URL, which implies contacting the customer that a retry does not actually do.
    Modelling an automatic retry as a customer-facing link overstated what the action was. The second
    reason is what forced the question: test-mode accounts cap Payment Links at 30 for the account's
    lifetime, and firing retries consumed that quota twice as fast as before. The cap is real and was
    hit; the primitive it pushed us toward is the more correct one anyway.

    Returns the new entity's details, or None if the create/fetch round-trip couldn't complete (rate
    limit exhausted, quota reached) -- a failed action is recorded as such, not silently treated as
    fired.
    """
    order = with_backoff(
        lambda: client.order.create({
            "amount": original_link["amount"],
            "currency": original_link["currency"],
            # The merchant-side reference field, which is exactly what it's for: this order is
            # attempt N against that original mandate.
            "receipt": f"retry-{attempt_number}-{original_link['id']}"[:40],
            "notes": {
                "project": "adaptive-mandate-recovery-engine",
                "purpose": "retry-action-fired",
                "original_payment_link_id": original_link["id"],
                "attempt_number": str(attempt_number),
                "rule_id": decision.rule_id,
                "scheduled_retry_at": decision.scheduled_retry_at.isoformat()
                    if decision.scheduled_retry_at else "",
            },
        }),
        f"fire retry action for case {case_index + 1}",
    )
    if order is None:
        return None

    # Re-fetch rather than trusting the create response -- same round-trip discipline the original
    # entity gets, so "this order exists on Razorpay's side" is verified, not assumed.
    fetched = with_backoff(
        lambda: client.order.fetch(order["id"]),
        f"confirm retry action for case {case_index + 1}",
    )
    if fetched is None:
        return None

    return {
        "retry_order_id": fetched["id"],
        "retry_receipt": fetched.get("receipt"),
        "retry_status": fetched.get("status"),
        "retry_amount_paise": fetched.get("amount"),
        "retry_created_at": datetime.fromtimestamp(
            fetched["created_at"], tz=timezone.utc
        ).isoformat(),
        "note": "created immediately for demonstration; a production system would create this at "
                "scheduled_retry_at, not at decision time",
    }


def _load_existing_links(client, wanted: int, min_amount_inr: float = 0.0) -> list[dict]:
    """Pulls real payment links that already exist on the account.

    Deliberately reads rather than creates, for two reasons. The honest one first: a recovery system
    does not create the failed payment it is recovering -- it reacts to one that already exists, and
    the original version of this batch creating its own subjects was the less faithful model. The
    forcing one second: test-mode accounts cap Payment Links at 30 for the account's lifetime and that
    cap is now reached (entry 25), so a create-first batch is not re-runnable on this account at all,
    which would have made the whole thing undemonstrable on camera.

    Reading existing entities makes the batch idempotent and re-runnable indefinitely. The one thing
    it costs: the mix of amounts is whatever the account happens to hold, rather than a set chosen to
    straddle the OTP ceiling -- hence `min_amount_inr`, so the above-ceiling path can still be pointed
    at directly rather than requiring a full-account scan to reach the large entities.
    """
    out: list[dict] = []
    skip = 0
    while True:
        page = client.payment_link.all({"count": 100, "skip": skip})
        items = page.get("payment_links", [])
        if not items:
            break
        out.extend(i for i in items if i["amount"] / 100 >= min_amount_inr)
        skip += len(items)
        if len(items) < 100 or len(out) >= wanted:
            break
    return out[:wanted]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the policy against real Razorpay entities")
    parser.add_argument("--count", type=int, default=9)
    parser.add_argument(
        "--min-amount", type=float, default=0.0,
        help="Only consider entities at or above this INR amount. Exists so the above-ceiling "
             "behaviour (A6: over INR 15,000 must escalate, never auto-retry) can be demonstrated "
             "directly instead of requiring a full-account run to reach the large entities.",
    )
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
    print("  Every entity below is read back from Razorpay's test-mode API, and every compliant")
    print("  retry decision fires a real Order against it. Decisions are tagged")
    print("  source=live_test_mode and are NOT counted in any recovery-rate or lift figure. See A30.")
    print("=" * 90)
    print()

    error_reasons = list(TEST_CARDS_BY_ERROR_REASON.keys())

    links = _load_existing_links(client, args.count, args.min_amount)
    if not links:
        if args.min_amount > 0:
            print(f"  No payment links at or above INR {args.min_amount:,.2f} on this account.")
        else:
            print("  No existing payment links found on this account. Create one first with:")
            print("    python -m integration.razorpay_test_mode.create_test_payment_link")
        print()
        return

    # Sorted by amount so the run reads in a sensible order and the above-ceiling cases (which must
    # escalate rather than retry) land together at the end where they're easy to point at.
    links.sort(key=lambda x: x["amount"])
    read = 0

    for i, link in enumerate(links):
        amount_inr = link["amount"] / 100

        if i > 0:
            time.sleep(INTER_CALL_DELAY_SECONDS)

        # 1. Real API read -- round-trip against the live API, not a cached local object.
        fetched = _with_backoff(
            lambda: client.payment_link.fetch(link["id"]), f"fetch payment link {i + 1}"
        )
        if fetched is None:
            continue
        read += 1

        # 2. Map a documented Razorpay decline code onto the failure taxonomy. Unpaid links carry no
        #    decline code of their own, so each case is assigned one of Razorpay's published
        #    error_reason values in rotation -- the mapping under test is the taxonomy join, and it
        #    is exercised against the real code strings rather than invented ones.
        error_reason = error_reasons[i % len(error_reasons)]
        failure_class = map_error_reason(error_reason)

        if failure_class is None:
            print(f"  [{i + 1:2d}] {fetched['id']:22s} INR {amount_inr:>9,.2f}  "
                  f"{error_reason:34s} -> not recoverable by retry, no policy decision")
            continue

        # 3. Real entity -> policy input. The policy cannot tell this apart from simulator output,
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

        # 4. Same compliance invariants as the simulated path.
        checks = evaluate_all(
            ProposedDecision(
                mandate_id=mandate.mandate_id,
                amount_inr=amount_inr,
                scheduled_retry_at=decision.scheduled_retry_at,
                notification_sent_at=decision.notification_to_send_at,
            ),
            config,
        )

        # 5. The veto -- same one eval/harness.py applies, and until entry 25 this file skipped it
        #    (see apply_compliance_veto's docstring). A decision that reaches step 7 below is
        #    compliant by construction, never by re-checking there.
        recorded_type = apply_compliance_veto(decision.decision_type, checks)

        # 6. Execute. A compliant RETRY_SCHEDULED decision fires a real new entity; anything else
        #    (escalate, stop, or a retry the veto just blocked) fires nothing, matching what a real
        #    system would do -- and proving the veto by absence, not just by the recorded label.
        fired = None
        if recorded_type == DecisionType.RETRY_SCHEDULED:
            fired = _fire_retry_action(
                client, _with_backoff, i, fetched, decision, attempt_number=2,
            )
            if i < args.count - 1:
                time.sleep(INTER_CALL_DELAY_SECONDS)

        action_metadata = (
            {"action_fired": True, **fired} if fired
            else {"action_fired": False}
        )

        # 7. Same audit schema, different source tag.
        log.append(DecisionRecord(
            decision_id=f"live_{fetched['id']}",
            mandate_id=fetched["id"],
            policy_name=policy.name,
            decision_type=recorded_type,
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
                **action_metadata,
            },
        ))

        fired_tag = " [ACTION FIRED]" if fired else ""
        print(f"  [{i + 1:2d}] {fetched['id']:22s} INR {amount_inr:>9,.2f}  "
              f"{error_reason:34s} -> {recorded_type.value:22s} {decision.rule_id}{fired_tag}")

    log.write_jsonl(OUT_PATH)

    escalations = sum(
        1 for r in log if r.escalation_action is not None
    )
    fired_count = sum(1 for r in log if r.metadata.get("action_fired"))
    blocked_count = sum(1 for r in log if r.decision_type == DecisionType.BLOCKED_BY_COMPLIANCE)
    print()
    print("-" * 90)
    print(f"  real entities read back via the live API    : {read}")
    print(f"  policy decisions recorded                  : {len(log)}")
    print(f"  retry actions actually fired                : {fired_count}")
    print(f"  compliant escalations                       : {escalations}")
    print(f"  retries blocked by compliance veto           : {blocked_count}")
    print(f"  compliance violations                       : {len(log.compliance_failures())}")
    print(f"  written to                                   : {OUT_PATH.relative_to(Path.cwd())}")
    print("-" * 90)
    print()


if __name__ == "__main__":
    main()
