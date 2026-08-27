"""Adaptive policy -- deterministic, context-aware, LLM-free.

Every decision here is a rule with an ID that lands in the audit trail. No model, no scoring
function, no learned weights: a reviewer can read this file and predict exactly what the system will
do for any input. That determinism is the point -- non-deterministic decisions about collecting money
are an audit and compliance liability, and the LLM's role is confined to narrating these decisions
after the fact (see narrator/).

**What this policy is allowed to know**, and why the comparison isn't circular:

  - The failure class. Real acquirers get decline codes; this is not privileged information.
  - The amount, the clock, the attempt history, when a notification was sent.
  - Public calendar knowledge: salary credits cluster near the 1st, the 7th, and month-end (A12,
    grounded in the Payment of Wages Act plus converging payroll-industry sources).
  - Public regulatory knowledge: the NPCI congestion window (A7) and the RBI ceilings (A6).

**What it must never know**, and does not receive on `PolicyState`:

  - The customer's simulated balance.
  - The ground-truth success probability of any attempt.
  - The customer's *individual* income-timing type. This is the crux of A13: population-level
    clustering is evidenced, but whether *this* customer is paid on the 7th is not knowable from
    any public source. So the policy makes a population-level bet and is wrong for the sizable
    fraction of customers who don't follow the pattern -- exactly as a real system would be.

If the policy could see the balance or the individual payday, it would be reading the answer sheet,
and any measured lift would be meaningless.
"""

from datetime import datetime, time, timedelta

from audit.decision_log_schema.records import DecisionType, EscalationAction
from compliance.invariants.rules import rbi_category_for
from policies.policy_interface.base import Decision, Policy, PolicyState
from simulator.mandate import UNRECOVERABLE_CLASSES, FailureClass

RULE_UNRECOVERABLE = "ADAPT-001"
RULE_OVER_CEILING_ESCALATE = "ADAPT-002"
RULE_ATTEMPTS_EXHAUSTED = "ADAPT-003"
RULE_AWAIT_INCOME_EVENT = "ADAPT-004"
RULE_AVOID_CONGESTION = "ADAPT-005"
RULE_RENOTIFY_AND_RETRY = "ADAPT-006"
RULE_TRANSIENT_RETRY = "ADAPT-007"

# Population-level income-event days of month (A12). Not this customer's payday -- see A13.
LIKELY_INCOME_DAYS_OF_MONTH = (1, 7, 28)

# Documented better windows are before 10:00, 13:00-17:00, and after 21:30 (A7). 14:00 sits inside
# the afternoon window with margin on both sides.
PREFERRED_RETRY_HOUR = 14
SETTLEMENT_BUFFER_DAYS = 1   # let an income credit actually land before debiting against it
MAX_WAIT_DAYS = 35           # never wait past one full monthly cycle


def _next_likely_income_day(after: datetime) -> datetime:
    """Next population-level income event strictly after `after`.

    Deliberately calendar arithmetic on public knowledge, not a per-customer prediction.
    """
    candidates = []
    for month_offset in (0, 1, 2):
        year = after.year + (after.month - 1 + month_offset) // 12
        month = (after.month - 1 + month_offset) % 12 + 1
        for dom in LIKELY_INCOME_DAYS_OF_MONTH:
            try:
                candidate = datetime(year, month, dom, PREFERRED_RETRY_HOUR)
            except ValueError:
                continue
            if candidate > after:
                candidates.append(candidate)
    return min(candidates)


def _avoid_congestion_window(when: datetime, config: dict) -> datetime:
    """Shift an attempt out of the documented NPCI deprioritisation window (A7).

    The window's existence and hours are documented; how much success actually degrades inside it is
    not published anywhere (A8). So the policy simply avoids it rather than pretending to quantify
    the penalty -- the right-sized response to a qualitative signal.
    """
    cfg = config["failure_classes"]["npci_congestion"]
    start_s, end_s = cfg["bad_window_local_time"]
    start = time(*(int(x) for x in start_s.split(":")))
    end = time(*(int(x) for x in end_s.split(":")))

    if start <= when.time() < end:
        return when.replace(hour=PREFERRED_RETRY_HOUR, minute=0, second=0, microsecond=0)
    return when


def _enforce_notification_floor(
    retry_at: datetime, notification_at: datetime, config: dict
) -> datetime:
    """RBI Clause 6(a): no debit within 24h of the pre-transaction notification being sent (A5).

    Enforced here so the policy proposes only compliant decisions in the first place. The invariant
    in compliance/ still independently vetoes anything non-compliant -- this is belt and braces, not
    a substitute for the veto.
    """
    min_hours = config["failure_classes"]["notification_undelivered"][
        "min_hours_between_notification_and_debit"
    ]["value"]
    floor = notification_at + timedelta(hours=min_hours)
    return max(retry_at, floor)


class AdaptivePolicy(Policy):
    name = "adaptive"

    def decide(self, state: PolicyState, config: dict) -> Decision:
        max_attempts = config["retry_policy_shared"]["max_attempts"]["value"]

        # --- Rule 1: unrecoverable failures. No timing strategy recovers these (A19).
        if state.failure_class in UNRECOVERABLE_CLASSES:
            return Decision(
                decision_type=DecisionType.STOPPED_UNRECOVERABLE,
                rule_id=RULE_UNRECOVERABLE,
                rule_description=(
                    f"{state.failure_class.value} is unrecoverable by retry timing; stop immediately "
                    "and escalate rather than spending attempts"
                ),
                escalation_action=(
                    EscalationAction.REQUEST_REMANDATE
                    if state.failure_class == FailureClass.MANDATE_EXPIRED
                    else EscalationAction.NO_ACTION_POSSIBLE
                ),
            )

        # --- Rule 2: above the no-OTP ceiling, an auto-retry is not legally available (A6).
        # Proposing one wastes an attempt on something that must be refused. The compliant action is
        # to ask the customer to re-authenticate.
        ceiling_cfg = config["compliance_floors"]["otp_free_ceiling_inr"]
        ceiling = ceiling_cfg["value"]
        # A6's higher ceiling is written in RBI's category names, not this project's product names,
        # so the two have to be translated before they can be compared. Comparing them directly --
        # which is what this did until entry 26 -- silently never matched, because no AmountType value
        # is ever spelled "mutual_funds". The mapping lives in compliance/ with the rest of the
        # regulatory knowledge, so the policy and the invariant cannot drift apart on it.
        if rbi_category_for(state.mandate.amount_type.value) in ceiling_cfg["higher_ceiling_categories"]:
            ceiling = ceiling_cfg["higher_ceiling_inr"]

        if state.mandate.amount_inr > ceiling:
            return Decision(
                decision_type=DecisionType.ESCALATED,
                rule_id=RULE_OVER_CEILING_ESCALATE,
                rule_description=(
                    f"Amount INR {state.mandate.amount_inr:,.2f} exceeds the INR {ceiling:,} "
                    "no-OTP ceiling; additional factor authentication is required, so request "
                    "re-authentication instead of an auto-retry that must be refused"
                ),
                escalation_action=EscalationAction.REQUEST_ADDITIONAL_AUTHENTICATION,
            )

        # --- Rule 3: the documented halt condition (A20). Same cap as baseline -- adaptive must win
        # by placing the same finite budget better, never by taking more shots.
        if state.attempt_number >= max_attempts:
            return Decision(
                decision_type=DecisionType.STOPPED_ATTEMPTS_EXHAUSTED,
                rule_id=RULE_ATTEMPTS_EXHAUSTED,
                rule_description=f"Attempt cap of {max_attempts} reached; stop and escalate",
                escalation_action=EscalationAction.NOTIFY_CUSTOMER_MANUAL_PAYMENT,
            )

        notification_at = state.failed_at
        rule_id, rule_description, retry_at = self._schedule(state, config, notification_at)

        retry_at = _avoid_congestion_window(retry_at, config)
        retry_at = _enforce_notification_floor(retry_at, notification_at, config)

        return Decision(
            decision_type=DecisionType.RETRY_SCHEDULED,
            rule_id=rule_id,
            rule_description=rule_description,
            scheduled_retry_at=retry_at,
            notification_to_send_at=notification_at,
        )

    def _schedule(
        self, state: PolicyState, config: dict, notification_at: datetime
    ) -> tuple[str, str, datetime]:
        """Failure-class-specific timing. This is where 'adaptive' actually differs from 'fixed'."""

        if state.failure_class == FailureClass.INSUFFICIENT_FUNDS:
            # The population-level bet (A12/A13): the customer is more likely to be able to pay
            # shortly after a typical income event. We do not know this customer's payday and never
            # claim to -- we are wrong for everyone who doesn't follow the pattern.
            income_day = _next_likely_income_day(state.failed_at)
            retry_at = income_day + timedelta(days=SETTLEMENT_BUFFER_DAYS)
            latest = state.failed_at + timedelta(days=MAX_WAIT_DAYS)
            retry_at = min(retry_at, latest)
            return (
                RULE_AWAIT_INCOME_EVENT,
                (
                    "Insufficient funds: wait until after the next population-level income event "
                    f"({income_day.date()}) plus a {SETTLEMENT_BUFFER_DAYS}-day settlement buffer, "
                    "rather than retrying into the same empty account"
                ),
                retry_at,
            )

        if state.failure_class == FailureClass.NPCI_CONGESTION:
            # Congestion is a time-of-day effect, not a funds problem -- no reason to wait days.
            retry_at = (state.failed_at + timedelta(days=1)).replace(
                hour=PREFERRED_RETRY_HOUR, minute=0, second=0, microsecond=0
            )
            return (
                RULE_AVOID_CONGESTION,
                (
                    "NPCI congestion: reschedule into a documented lower-traffic window "
                    f"({PREFERRED_RETRY_HOUR}:00) rather than repeating the peak-hour attempt"
                ),
                retry_at,
            )

        if state.failure_class == FailureClass.NOTIFICATION_UNDELIVERED:
            # Re-send the notification, then respect the full 24h floor before debiting. The wait is
            # a legal requirement (A5), not a heuristic -- and the audit trail says so.
            retry_at = notification_at + timedelta(hours=25)
            return (
                RULE_RENOTIFY_AND_RETRY,
                (
                    "Notification undelivered: re-send the pre-transaction notification and wait the "
                    "mandatory 24h before the next debit (RBI Clause 6(a))"
                ),
                retry_at,
            )

        # bank_technical_decline: transient by definition (A31), so retry as soon as the compliance
        # floor allows rather than burning calendar time.
        retry_at = notification_at + timedelta(hours=25)
        return (
            RULE_TRANSIENT_RETRY,
            (
                "Bank technical decline is transient: retry as soon as the 24h notification floor "
                "permits, without spending additional calendar time"
            ),
            retry_at,
        )
