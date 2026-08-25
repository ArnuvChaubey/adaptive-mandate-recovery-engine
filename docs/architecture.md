# Architecture

The organising principle: **the simulator models the world, policies decide what to do about it, and
neither can see into the other.** Every structural decision below exists to make that boundary
verifiable by a reviewer rather than trusted on assertion.

## Data flow

```
config/sim_params.yaml  (frozen, hashed)
        │
        │  load_config() refuses to run if meta.frozen is false
        ▼
   simulator/                                    ground truth
   ├── batch.py ............ generates Mandates (amount, type, income timing, validity)
   ├── balance_evolution/ .. daily balance from income events + decay
   ├── population/ ......... income-event calendars per customer type
   └── failure_events/ ..... true success probability for a given attempt
        │
        │  Mandate ──► MandateView.from_mandate()   ◄── REDACTION BOUNDARY
        │              drops income_timing_type
        ▼
   policies/                                     decisions
   └── decide(PolicyState, config) -> Decision{retry_at | escalate}
        │
        ▼
   compliance/invariants/                        veto
   └── evaluate_all() -> [ComplianceCheck]
        │  a non-compliant retry is NOT executed; the proposal is still logged
        ▼
   audit/decision_log_schema/                    the record
   └── DecisionRecord{rule_id, checks, source: simulation | live_test_mode}
        │
        ├──────────────► eval/           metrics, lift decomposition, sensitivity sweep
        │
        └──────────────► narrator/       reads only; never writes back
```

## Components

### `simulator/`
Generates mandate-failure events. Every non-directly-sourced parameter is read from a swept range in
the frozen config and tagged with its `assumptions.md` ID — there are no bare numeric literals in the
simulation path.

`balance_evolution/` is deliberately isolated as its own module: it is the largest assumption cluster
in the project (A14/A15, both LOW confidence) and should be the easiest thing in the repo for a
skeptic to find, interrogate, and replace.

A failure event is always **consistent with its own cause** — an insufficient-funds failure happens on
a day the balance is actually short, a congestion failure happens inside the documented congestion
window, an expiry failure happens at or after expiry. An earlier version assigned failure classes
independently of world state and produced an incoherent simulation that recovered 89% of everything.

### `policies/`
One contract: `decide(state, config) -> Decision`. The harness knows nothing else about any policy,
which is what makes "policy-agnostic" an architectural fact rather than a marketing line.

| policy | role |
|---|---|
| `baseline_policy` | fixed cadence, failure-class blind, stops at the documented 4-attempt cap |
| `compliance_aware_baseline` | ablation: baseline + over-ceiling escalation only, isolating how much lift is compliance rather than intelligence |
| `adaptive_policy` | deterministic, context-aware; times retries by failure class, avoids the congestion window, escalates above the OTP ceiling |
| `adaptive_hedged_policy` | iteration on the above: probes early before committing to the income-event bet |
| `external_policy_stub` | deliberately unimplemented — see below |

A `Decision` that stops **must** name an escalation action; the dataclass raises otherwise. "Compliant
escalation" means stopping with a next step, not giving up, so the type system enforces it.

`external_policy_stub` raises `NotImplementedError` and is never registered in any run. It exists so
that assumption A26 — that "policy-agnostic" is a design property and *not* a demonstration against
Razorpay's real engine, which exposes no callable interface — is visible in the architecture instead
of implied away.

### The redaction boundary
`Mandate` (simulator side) carries `income_timing_type`: whether this customer is actually paid on the
1st, the 7th, or irregularly. `MandateView` (policy side) does not have that field.

This is the single most load-bearing structural decision in the project. The adaptive policy bets on a
*population-level* salary pattern (A12, evidenced) and is necessarily wrong for customers who don't
follow it (A13, unknowable from any public source). If a policy could read the individual's true
pattern, it would be scheduling against the answer sheet and every lift number would be meaningless.

Enforced by the type, not by convention. A test asserts the field's absence on the view and its
presence on the full object.

### `compliance/invariants/`
Two invariants, each traceable to a citable clause:

- `INV-RBI-6a-NOTIFICATION-TIMING` — no debit scheduled within 24h of the pre-transaction notification
  being **sent**. RBI E-mandate Framework 2026, Clause 6(a).
- `INV-RBI-OTP-CEILING` — auto-debit without additional factor authentication capped at ₹15,000
  (₹1 lakh for insurance / mutual funds / credit-card bills).

Deliberately outside `policies/`, so a reviewer verifies that no policy bypasses a floor by reading
one small module rather than auditing every policy — including ones added later.

An invariant we cannot quote a clause for does not belong here. That rule exists because an earlier
version enforced an auto-block on undelivered notifications that the framework does not actually
require (A4, refuted).

Checks carry `applicable` as well as `passed`: a rule that did not apply to a decision is not a rule
that was satisfied, and conflating them makes the audit trail read misleadingly.

### `audit/decision_log_schema/`
One `DecisionRecord` per decision: the rule ID that fired, its description, the failure class, the
amount, every compliance check evaluated (passing ones included — the difference between "we never
violated the rule" and "we never tested it"), and a `source` tag.

Simulated and live decisions share one schema, so the same queries work over both while no reader can
mistake one for the other.

### `eval/`
- `metrics/definitions.py` — every metric formally defined **before** anything was computed against
  it. Both recovery-rate denominators are returned by one function so reporting only the flattering
  one is structurally awkward.
- `harness.py` — runs a batch through a policy. Owns the compliance veto and the escalation-response
  model.
- `run_eval.py` — the single reproducibility entrypoint.
- `sensitivity.py` — 19 scenarios pinning declared assumption ranges to specific points; reports the
  distribution and the conservative headline, never the maximum.
- `redteam.py` — hands Claude the assumption table and the frozen config and asks it to find
  parameterisations where the policy loses. Proposals are validated against the schema and the
  declared ranges before they can run; the verdict comes from the metrics. A hallucinated attack
  costs a wasted scenario, never a false result.
- `report.py` — self-contained HTML batch report, including the metric the policy loses on.

### `audit/query.py`
Natural-language interrogation of the decision log. The model translates a question into a
restricted, validated `QuerySpec`; deterministic code executes it. The model never sees the records
and is never asked for a number. Unknown query fields are *rejected* rather than ignored, because a
silently-dropped filter answers a wider question than the one asked.

### `narrator/`
Reads the audit log after the fact. Deterministic templates are the primary path; the LLM rewrites
them; a mechanical validator rejects any output introducing an ungrounded number, a missing rule
citation, a prohibited claim, a truncated response, or a dropped customer message. Removing the
directory changes no result in the project.

### `integration/razorpay_test_mode/`
Real API client (refuses non-`rzp_test_` keys), webhook receiver with HMAC-SHA256 signature
verification, and `live_batch.py`, which runs the real policy engine against real Razorpay entities
with documented decline codes mapped onto the failure taxonomy. Rate-limit backoff degrades the batch
rather than aborting it.

## Rubric mapping

| Track 03 clause | Where it lives |
|---|---|
| measured money recovered | `eval/metrics/definitions.py` — ₹ recovered, frozen ε, both denominators |
| across a batch | `eval/run_eval.py` — 30 seeds × 200 mandates; `eval/sensitivity.py` — × 15 scenarios |
| compliant escalation | `compliance/invariants/` + `EscalationAction` required on every stop decision |
| stopping rules | 4-attempt cap (documented halt condition), unrecoverable-class stops, compliance veto |
| audit trail | `audit/decision_log_schema/` — rule-linked, LLM-independent, JSONL-exportable |
