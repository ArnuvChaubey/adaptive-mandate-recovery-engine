# Adaptive Mandate Recovery Engine

An open, auditable, reproducible **evaluation harness** for recurring-payment recovery policies.

Built for Razorpay's AI Buildathon, Track 03 — AI Revenue Recovery.

---

## The claim, stated conservatively

Against the **strongest** fixed-retry baseline we could construct, a deterministic context-aware
policy recovers **+12.5% more mandates and +89.9% more value**, holds up across **19 of 19**
sensitivity scenarios and **16 more scenarios an LLM generated specifically to break it**, captures
**95.2%** of the theoretical recovery ceiling — and **loses** on wasted attempts.

That last clause is not an oversight. It is the result.

> **Every figure in this repository is a simulated-batch statistic**, computed from a frozen,
> version-controlled config and a fixed seed list. Nothing here is measured against real transaction
> data, and no number is a revenue forecast. See [Honest limits](#honest-limits).

---

## Why this exists

Razorpay's own **Intelligent Retry Engine** (beta, FTX 2026) already validates the thesis that
fixed-interval retry is the wrong model — its materials describe traditional retry as "rigid" and
firing "at fixed intervals without understanding user context, bank availability, or merchant
priorities."

What it does not publish: any decision methodology, whether it is rule-based or ML-driven, any
recovery-rate or lift figure, or an audit trail. It ships as a configurable black box that invites
merchants to "define retry cadence" without telling them what a given cadence costs.

**This project is not a claim to have invented adaptive retry.** It is the measurement layer that
such a system does not currently expose: a policy-agnostic harness that scores any retry policy
against frozen ground truth, decomposes where the gain actually comes from, sweeps the result across
every uncertain assumption, and ties every decision to a rule in an auditable log.

Full positioning, including what this framing does *not* support: [docs/positioning.md](docs/positioning.md).

---

## Results

30 seeds × 200 mandates = 6,000 simulated mandates, ₹52.75M of mandate value, every mandate identical
across every policy (see [matched worlds](#how-it-is-kept-honest) below).

| | baseline | + compliance aware | adaptive | adaptive hedged | oracle |
|---|---|---|---|---|---|
| recovery rate (recoverable) | 56.9% | 63.7% | **78.0%** | 74.4% | 81.9% *(ceiling)* |
| recovery rate (all mandates) | 51.5% | 57.7% | **70.6%** | 67.3% | 74.2% *(ceiling)* |
| value recovered | ₹9.39M | ₹19.07M | **₹21.30M** | ₹20.80M | ₹21.87M *(ceiling)* |
| wasted attempt rate | 0.8% | 0.8% | 1.9% | 1.4% | **0.0%** *(ceiling)* |
| median days to recovery | **1.0** | **1.0** | 3.2 | **1.0** | **1.0** |
| non-compliant proposals blocked | 22.8% | 0.0% | 0.0% | 0.0% | 0.0% |

The oracle is **not a deployable candidate**. It sees the customer's true balance trajectory —
something no real system ever could — and picks the objectively best remaining attempt day within the
identical 4-attempt cap and compliance floors every other policy respects. Its only job is to answer a
question the table above can't: *is 78% good?* See [How far from the ceiling](#how-far-from-the-ceiling) below.

### The lift is decomposed, not asserted

The adaptive policy escalates amounts above the ₹15,000 no-OTP ceiling instead of firing retries that
must legally be refused. A fair reviewer will say: *that is a compliance check any real system already
has, not intelligence.* They would be right — so we built the ablation that separates it.

| | recovery rate | value |
|---|---|---|
| compliance awareness alone | +12.0% | +103.1% |
| retry timing alone | +22.4% | +11.7% |
| **total** | **+37.1%** | **+126.9%** |

If you believe production systems already check the ceiling, the honest claim is the **timing-only**
row, not the total. Both are reported; you decide.

### How far from the ceiling?

`baseline → adaptive → oracle` isn't three points, it's a spectrum, and the harness scores all of it
the same way — which directly answers the "cathedral evaluating a shed" objection: this apparatus
isn't sized for one clever heuristic, it's sized for a family of policies including the one that
defines how much headroom is even left.

```
adaptive captures 95.2% of the oracle's recovery rate
oracle wasted-attempt rate: 0.0%  (it only retries on a day it already knows will work)
```

This is a **recovery-maximising** ceiling specifically, not a simultaneous ceiling on every metric —
the attempt sequence that maximises recovery probability isn't necessarily the one that minimises
waste or time-to-recovery. And it's a *narrow* ceiling by design: tracing every failure-class's
success-probability function shows day-of-attempt timing only changes ground truth for two of six
classes — `insufficient_funds` (the balance curve) and `npci_congestion` (already fully solved by
adaptive's existing avoidance rule once the retry hour is fixed outside the bad window). So the oracle
can *only* beat adaptive on one dimension, and it does — for the other five, adaptive is already at
the ceiling, which the oracle confirms by matching it there rather than mysteriously winning
everywhere for reasons nobody could point to.

The full report ([`eval/reports/examples/report_example.html`](eval/reports/examples/report_example.html))
renders this as two charts: a **95-point scatter** (19 scenarios × 5 policies — enough density to show
an actual frontier shape, not five dots) plotting recovery against waste, and a **radar chart** across
four normalised axes (recovery, waste, revocations, speed) showing that no policy's shape covers the
full square — recovery and speed pull one way, waste and revocations pull another.

### It survives the assumption ranges

19 scenarios, each pinning a LOW-confidence assumption to a specific point within its already-declared
range — five different baseline retry cadences, the escalation response rate at both extremes, three
failure-class mixes, and a population where most customers have no salary cycle at all.

```
recovery-rate lift positive in   19/19 scenarios   +10.3% to +54.7%   median +33.1%
value lift positive in           19/19 scenarios   +65.2% to +182.3%
wasted attempts IMPROVED in       1/19 scenarios

CONSERVATIVE HEADLINE (vs the strongest baseline):  +12.5% rate, +89.9% value
```

Then 16 more scenarios generated by Claude with instructions to *break* it (see below): **none
landed**, and the weakest result it found was **+5.7%** — harder than anything we wrote ourselves.

The headline is the **strongest** baseline, not the documented one. Measurement showed our original
next-day-retry baseline was the *weakest* plausible schedule — we had built a strawman while believing
we were being conservative. Fixing it cut the lift from ~+36% to the conservative figure above.
([build log, entry 13](docs/build_log.md))

### Where it loses

The adaptive policy wastes **more** attempts than baseline in most scenarios. All of it sits in
`insufficient_funds`: waiting for a likely payday wins for customers who follow the pattern and fires
into a drained account for the 20–40% who don't. It converts near-miss failures into confident misses.
That is the measurable cost of assumption A13, flagged as high-risk on day one — and it's precisely
what the oracle *doesn't* pay, since it isn't guessing.

The hedged variant halves that regression and cuts median recovery time from 3.2 days to 1.0 — and
costs several points of recovery lift, because the extra attempt more than **doubles** customer-initiated
revocations. Neither policy dominates. Both ship, and the trade-off is the finding.

---

## Reproduce it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m eval.run_eval --policies baseline,compliance_aware_baseline,adaptive,adaptive_hedged,oracle \
                        --seeds config/seeds.txt --n-mandates 200
python -m eval.sensitivity --seeds 10 --n-mandates 200
```

No number in this README, the pitch video, or the demo came from anywhere but those two commands.
`config/sim_params.yaml` records the commit hash it was frozen at, and `simulator/config_loader.py`
**refuses to run** against a config that is not frozen and hashed.

A self-contained HTML batch report — the money, the comparison, the sensitivity verdict, and real
audit records from both the simulator and the live API:

```bash
python -m eval.report        # writes eval/reports/report.html
```

A committed snapshot lives at
[`eval/reports/examples/report_example.html`](eval/reports/examples/report_example.html) so it can be
read without running anything.

Optional, needs credentials in `.env` (see `.env.example`):

```bash
python -m integration.razorpay_test_mode.live_batch --count 12   # real Razorpay test-mode API
python -m narrator.narrate --limit 6                             # decision narration

# the closed loop: real webhook -> signature check -> policy -> compliance -> audit -> narration
uvicorn integration.razorpay_test_mode.webhook_receiver:app --port 8010
```

The receiver is the loop, not a logger. A verified Razorpay event goes through the same policy
engine, the same compliance invariants, and the same audit schema as the simulator — the policy
cannot tell the difference. `GET /state` shows decisions, recovered value, and compliance violations
live. A forged signature is rejected with a 400 before anything is parsed.

---

## How it is kept honest

**Every policy faces the identical batch of mandates.** Found broken while building the oracle: the
harness originally used one continuously-advancing RNG stream across a whole batch, so as soon as two
policies took different numbers of attempts, the stream drifted and every mandate after the first
divergence became a *different synthetic scenario* between runs — confirmed at 30 of 50 mandates
mismatched for the "same" seed. Each mandate now gets its own RNG keyed by `(seed, index)`,
independent of every other mandate in the batch. A regression test pins 0 mismatches across all five
policies. ([build log, entry 21](docs/build_log.md))

**Ground truth is frozen before any policy exists.** `config/sim_params.yaml` was committed and
hashed before a single line of policy code was written. Changing it requires a dated CHANGELOG entry
in [assumptions.md](assumptions.md) stating whether results had already been observed. There are six
such entries, including one that made our own headline number materially worse.

**Metrics are defined before they are computed.** "Wasted attempt" — an attempt fired when
ground-truth success probability was ≤ ε — was specified with ε frozen in config on day 4, before any
adaptive policy existed. It has never been redefined, which is why the project reports a metric it
loses on.

**Policies cannot read the answer sheet.** Policies receive a redacted `MandateView` that structurally
omits `income_timing_type` — the customer's actual salary pattern. Not by convention: the field does
not exist on the type, and a test asserts its absence. Every lift number depends on that boundary.

**Compliance is a veto, not a note.** The harness refuses to execute a non-compliant retry regardless
of what a policy asked for; the proposal is still logged as `blocked_by_compliance`. Invariants live
outside `policies/` so one small module can be audited instead of every policy. Tests fail on
deliberate violations.

**Every claim is graded.** 35 assumptions in [assumptions.md](assumptions.md), each with evidence,
confidence, simulator impact, and challenge risk. One (A4) is marked **REFUTED** and struck through
rather than deleted, because we asserted a regulation the RBI framework does not contain and the
correction should be as auditable as the claim.

---

## Architecture

```
simulator/     six failure classes, balance evolution, population income timing
policies/      shared decide() contract -- baseline, compliance-aware, adaptive, hedged, oracle, external stub
compliance/    RBI invariants, enforced as a veto, outside policy code
audit/         structured decision log (LLM-independent) + NL query layer
eval/          frozen metrics, harness, reproducibility entrypoint, sensitivity sweep, red team, frontier charts
narrator/      deterministic templates + optional LLM polish + grounding validator
integration/   real Razorpay test-mode API, idempotent webhook loop
```

Detail: [docs/architecture.md](docs/architecture.md).

### Two places the LLM does real work — neither of them a decision

**It attacks our results.** `eval/redteam.py` hands Claude the assumption table and the frozen config
and asks it to find parameterisations where the adaptive policy *loses*. It proposes; the harness
disposes. Every scenario is mechanically validated against the ranges already declared in
`sim_params.yaml` before it can run, and the verdict comes from the metrics, not the model — so a
hallucinated attack costs a wasted scenario, never a false result.

Across 16 generated attacks: **0 landed**, weakest **+5.7%** — below the +10.0% floor of all our
hand-written scenarios. The model found harder attacks than we did. It also caught a real methodology
error in *our own* scenarios: we required it to stay inside declared ranges while
`mostly_irregular_income` quietly did not. That scenario is now labelled out-of-range, and the honest
in-range version was added.

```bash
python -m eval.redteam --count 10
```

**It makes the audit trail interrogable.** `audit/query.py` turns an English question into a
structured `QuerySpec` that deterministic code executes over the records. The model never sees the
data and is never asked for a number, so it cannot invent one.

```bash
python -m audit.query "what did we escalate above the OTP ceiling?"
python -m audit.query "which decisions did compliance block?"
```

### Where the LLM is, and is not

The LLM makes **no decisions**. Every retry, stop, and escalation comes from deterministic rules with
IDs that land in the audit log. The narrator reads that log *after the fact* and turns records into
prose — and even there it is not the primary path: deterministic templates produce the narration, the
LLM rewrites it more fluently, and a mechanical validator discards any output that introduces a
number, date, or claim the record does not support. Delete `narrator/` entirely and every result in
this README is unchanged.

A live run against the real API caught this earning its keep: a truncated response was still perfectly
*grounded*, passed validation, and silently dropped a required customer message. The guard now checks
for omission as well as invention. ([build log, entry 15](docs/build_log.md))

---

## Honest limits

- **Not measured against real transaction data.** Every recovery-rate, lift, and ₹ figure is a
  simulated-batch statistic from the frozen config. It demonstrates a measurement methodology, not a
  revenue outcome.
- **Not benchmarked against Razorpay's Intelligent Retry Engine.** It exposes no public callable
  interface. `policies/external_policy_stub/` exists to make that limitation visible in the
  architecture rather than imply it away (A26).
- **The live test-mode batch proves integration, not performance.** 9 real entities, real API
  round-trips, real decline-code mapping, real policy decisions, `source: live_test_mode`. It is not a
  statistical sample and never appears beside a recovery-rate figure (A30). A scripted 15–20 case
  *completed-payment* batch is not possible on a standard test account — checkout requires a human,
  S2S requires Razorpay to enable it, and no payment-simulation endpoint exists.
- **The biggest single-parameter risk is A35**, the escalation response rate, which carries the ₹
  headline and has no public source. It is applied identically to every policy so it cannot
  manufacture lift, and it is swept — but it is the number to attack first.
- **The retry cadence of real production systems is unpublished** (A1). The baseline is an informed
  construction, not a reproduction of Razorpay's behaviour.

---

## What broke along the way

[docs/build_log.md](docs/build_log.md) — written as it happened. Includes a two-day payment wall that
turned out to be a server-side failure in Razorpay's own test environment (proven from their signed
webhooks), a first result that was too good because of a modelling bug, a compliance check that
logged violations and executed them anyway, a sensitivity sweep that found two mechanisms silently
doing nothing, a prediction of ours that measurement disproved, and — while building the oracle — a
discovery that every policy comparison up to that point had been drawing from two independent
samples rather than one matched batch.
