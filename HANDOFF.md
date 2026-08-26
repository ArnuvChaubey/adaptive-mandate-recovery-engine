# HANDOFF — Adaptive Mandate Recovery Engine

**Read this entire file before touching anything.** This project's value is almost entirely
methodological, and several of its properties can be destroyed by a single well-intentioned edit.
Section 3 lists those specifically.

Written 2026-08-26. Deadline **5 September 2026**.

---

## 1. What this is, in one paragraph

An open, auditable, reproducible **evaluation harness** for recurring-payment mandate-recovery
policies, built for Razorpay's AI Buildathon Track 03 (AI Revenue Recovery). It is **not** a claim to
have invented adaptive retry — Razorpay already shipped an "Intelligent Retry Engine" (beta, FTX 2026)
that makes the same argument. It is the **measurement layer that engine does not publish**: a
policy-agnostic harness that scores any retry policy against frozen ground truth, decomposes where
the gain comes from, sweeps it across every uncertain assumption, lets an LLM attack the result, and
ties every decision to a rule in an auditable log.

Built as a submission for Razorpay's AI Buildathon Track 03 (AI Revenue Recovery), deadline
**5 September 2026**.

---

## 2. Hard facts

| | |
|---|---|
| Working dir | repo root |
| Repo | `github.com/ArnuvChaubey/adaptive-mandate-recovery-engine` |
| **Repo visibility** | **PRIVATE — must be flipped to PUBLIC before submission.** The form requires a public URL. Secret scan is clean; it is safe to flip. |
| Deadline | **5 September 2026**, applications close |
| Submission | Public GitHub repo + unlisted 5-min pitch video + 12-question Google Form (`forms.gle/d9r2gvxp8cmoZhon9`) |
| Commits | 36 |
| Tracked files | 96 |
| Python | 6,551 lines |
| Tests | **120 passing** (`python -m pytest tests/ -q`) |
| Assumptions | 36 documented (A4 REFUTED) |
| Build-log entries | 24 |
| Sensitivity scenarios | 19 + 5 AI-generated attacks (redteam count varies run to run) |
| Frozen config hash | `eaf9126d9797632f19829f6374e10806ca066b2d` |
| Working tree | clean, committed, **not yet pushed** |

**Judging criteria, verbatim from the site:** Problem taste ("did you pick something that actually
matters"), Build quality ("does it run, is it structured, would you trust it"), **AI judgment** ("the
right tool in the right place, **and where you chose not to use one**"), Failure recovery ("what
broke, and what you did about it").

**Track 03 bar, verbatim:** "Don't just identify the problem. Show measured money recovered across a
batch, with compliant escalation, stopping rules, and an audit trail."

---

## 3. ⚠️ THINGS THAT WILL DESTROY THIS PROJECT IF YOU GET THEM WRONG

### 3.1 `config/sim_params.yaml` is FROZEN
It was committed and hashed **before any policy code existed**. That fact is the entire credibility
argument. `simulator/config_loader.py` **refuses to run** against a config that isn't frozen and
hashed.

**If you change any value in it**, you must add a dated entry to the CHANGELOG at the bottom of
`assumptions.md` stating what changed, why, and **explicitly whether policy results had already been
observed**. There are six such entries; read them for the format. Then update
`meta.frozen_commit_hash` to the new commit.

Changing it silently is the single worst thing you can do here.

### 3.2 Policies must never see ground truth
Policies receive `MandateView`, a redacted projection that **structurally omits**
`income_timing_type` — the customer's real payday. Not by convention: the field does not exist on the
type, and `tests/test_policies.py::test_policy_state_cannot_expose_individual_income_timing` asserts
it. Every lift number depends on this. **Do not add fields to `MandateView` without understanding
this.**

### 3.3 Metrics were frozen before results
"Wasted attempt" (ε = 0.01, in config) was defined on day 4, before any adaptive policy existed —
specifically so it couldn't be redefined when it became inconvenient. **It did become inconvenient:
the adaptive policy loses on it.** That row stays in every report. Do not remove it, soften it, or
quietly drop it from the README. Reporting it is a major part of why this project is credible.

### 3.4 The headline is the CONSERVATIVE number
Report **+12.5% recovery-rate lift against the strongest baseline**, not the +37.1% total or the
+33.1% median. The original baseline (`[1]`, retry next day) turned out to be the *weakest* plausible
schedule — a strawman built by accident. Fixing it cut the headline by two-thirds and that is the
number we stand behind. See build log entry 13.

### 3.5 Never mix simulated and live numbers
Every recovery/lift/₹ figure is a **simulated-batch statistic** and must be labelled as such
everywhere. The live Razorpay test-mode work (9 entities + webhook loop) is an **integration proof
only** and must never appear beside a recovery-rate figure as if it supports it. This is assumption
A30 and it is load-bearing for honesty.

### 3.6 The LLM makes no decisions
Every retry/stop/escalate comes from deterministic rules with IDs. The LLM is used in exactly three
places, none of them a decision: narration (`narrator/`), adversarial scenario generation
(`eval/redteam.py`), and NL→query translation (`audit/query.py`). In all three, output is
mechanically validated and the model is never trusted as a source of fact. **Do not put a model in
the decision loop.** It is the single strongest answer to the "AI judgment" criterion.

---

## 4. The results

30 seeds × 200 mandates = 6,000 mandates, ₹52,750,073 batch value.

| | baseline | +compliance aware | adaptive | adaptive hedged |
|---|---|---|---|---|
| recovery rate (recoverable) | 56.9% | 63.7% | **78.0%** | 74.4% |
| recovery rate (all) | 51.5% | 57.7% | **70.6%** | 67.3% |
| value recovered | ₹9.39M | ₹19.07M | **₹21.30M** | ₹20.80M |
| wasted attempt rate | 0.8% | **0.8%** | 1.9% | 1.4% |
| median days to recovery | **1.0** | **1.0** | 3.2 | **1.0** |
| non-compliant proposals | 22.8% | **0%** | **0%** | **0%** |

**Additional recovered by adaptive vs baseline: ₹11,914,526.**

**Lift decomposition** (this exists because "adaptive escalates above the OTP ceiling" is a
*compliance check*, not intelligence — a fair reviewer would call that out, so we isolated it):

| source of gain | recovery rate | value |
|---|---|---|
| compliance awareness alone | +12.0% | +103.1% |
| retry timing alone | +22.4% | +11.7% |
| total | +37.1% | +126.9% |

**Sensitivity: 19/19 scenarios positive**, +10.3% to +54.7%, median +33.1%. Conservative headline
**+12.5%** vs strongest baseline.

**Red team: 5 AI-generated attacks, 0 landed**, weakest **+10.8%** — consistent with, not below, the
+10.3% floor of the current hand-written sensitivity sweep. (`docs/build_log.md` entry 15 records an
earlier run finding +5.7% against an 18-scenario sweep floor of +10.0% — a different sweep size, so
not directly comparable to this run. The red team is LLM-generated and its output is not guaranteed
stable run to run. Re-verify with `python -m eval.redteam` before quoting a specific number in the
video or form — don't just copy this one.)

**Throughput (measured, not estimated): 65,268 decisions/sec** single unoptimised core including
compliance checks. All-India UPI mandate execution averages ~312/sec, so one core is ~200× the
country's average load. The policy engine is not the bottleneck.

**Where it loses:** adaptive wastes more attempts than baseline in most scenarios. All of it is in
`insufficient_funds` — waiting for a likely payday wins for pattern-followers and fires into drained
accounts for the 20–40% who aren't (assumption A13). Hedging halves the regression and cuts recovery
time 3.5d → 1.0d, costing ~9 points of lift because the extra attempt **more than doubles
customer-initiated revocations (3.3% → 7.1%)**. Neither policy dominates; both ship.

---

## 5. Architecture

```
simulator/        6 failure classes, balance evolution, population income timing
  ├─ batch.py, mandate.py, config_loader.py (refuses unfrozen config)
  ├─ balance_evolution/   ← largest assumption cluster (A14/A15), isolated deliberately
  ├─ population/          ← income-event calendars, mixture over 3 customer types
  └─ failure_events/      ← true success probability per attempt

policies/         one decide() contract; harness knows nothing else
  ├─ policy_interface/    ← Policy ABC, PolicyState, Decision, MandateView (REDACTION BOUNDARY)
  ├─ baseline_policy/            BASE-001..003
  ├─ compliance_aware_baseline/  CABASE-002  ← ablation, exists to attack our own number
  ├─ adaptive_policy/            ADAPT-001..007
  ├─ adaptive_hedged_policy/     ADAPT-H-004A/B
  └─ external_policy_stub/       ← raises NotImplementedError BY DESIGN (A26)

compliance/invariants/   INV-RBI-6a-NOTIFICATION-TIMING, INV-RBI-OTP-CEILING
                         outside policies/ so non-bypassability is verifiable in one small file
audit/
  ├─ decision_log_schema/  DecisionRecord, DecisionLog, ComplianceCheck(applicable flag)
  └─ query.py              NL → validated QuerySpec → deterministic execution

eval/
  ├─ metrics/definitions.py  frozen metric definitions
  ├─ harness.py              runs batches, owns the COMPLIANCE VETO + escalation model
  ├─ run_eval.py             the single reproducibility entrypoint
  ├─ sensitivity.py          19 scenarios
  ├─ redteam.py              Claude attacks the results; harness adjudicates
  └─ report.py               self-contained HTML report

narrator/          templates.py (PRIMARY), llm_explainer/, validator.py (grounding guard)
integration/razorpay_test_mode/
  ├─ client.py               refuses non-rzp_test_ keys
  ├─ webhook_receiver.py     THE LIVE LOOP: verify → policy → compliance → audit → narrate
  ├─ live_pipeline.py        pure fn, tested against REAL captured payloads
  ├─ live_batch.py           real API batch with rate-limit backoff
  ├─ idempotency.py          dedupe on (event type, payment id)
  └─ failure_mapping.py      DOCUMENTED vs OBSERVED decline codes (different evidence grades)
```

**Data flow:** frozen config → simulator (ground truth) → `MandateView` redaction → policy decides →
compliance vetoes → audit record → eval metrics / narrator.

---

## 6. Every command

```bash
cd path/to/repo
source .venv/bin/activate

# tests
python -m pytest tests/ -q                                    # 104 passing

# the headline numbers
python -m eval.run_eval --policies baseline,compliance_aware_baseline,adaptive,adaptive_hedged \
                        --seeds config/seeds.txt --n-mandates 200

# sensitivity (19 scenarios)
python -m eval.sensitivity --seeds 10 --n-mandates 200 --candidate adaptive
python -m eval.sensitivity --seeds 10 --n-mandates 200 --candidate adaptive_hedged

# Claude attacks the results (needs ANTHROPIC_API_KEY)
python -m eval.redteam --count 10 --seeds 8 --n-mandates 200

# HTML report → eval/reports/report.html
python -m eval.report

# narration (works with or without ANTHROPIC_API_KEY)
python -m narrator.narrate --limit 6

# NL audit interrogation (needs ANTHROPIC_API_KEY)
python -m audit.query "what did we escalate above the OTP ceiling?"

# real Razorpay test-mode API
python integration/razorpay_test_mode/client.py                    # connectivity smoke test
python -m integration.razorpay_test_mode.live_batch --count 12
python -m integration.razorpay_test_mode.create_test_payment_link  # then pay it in a browser

# the live loop
uvicorn integration.razorpay_test_mode.webhook_receiver:app --port 8010
# GET /health  GET /state  POST /webhook
```

---

## 7. Credentials and environment

`.env` (gitignored, already populated) holds:
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — **test mode only**. Client refuses non-`rzp_test_` keys.
  These **do not expire**.
- `RAZORPAY_WEBHOOK_SECRET` — user-chosen string, must match the dashboard webhook config.
- `ANTHROPIC_API_KEY` — real billing. Needed for redteam, audit query, LLM narration.

**Never print these, never commit them, never paste them into chat.** A secret scan of the full git
history is clean (`.env` untracked, no live keys, no webhook secret, no ngrok token in any commit).

**Webhooks need a public HTTPS URL.** ngrok is installed and authenticated. The tunnel URL changes on
every restart, so the Razorpay dashboard webhook must be reconfigured each session:
Dashboard (Test Mode) → Account & Settings → Webhooks.

---

## 8. Assumptions — the ones that matter

36 total in `assumptions.md`, each with evidence, confidence, simulator impact, challenge risk.

| ID | Why it matters |
|---|---|
| **A1** | **Highest challenge risk.** Baseline retry cadence — no public source, and it sits on the *baseline* side of every lift number. Swept across 5 schedules; headline uses the strongest. |
| **A4** | **REFUTED.** We inherited "RBI blocks the debit if the notification is undelivered." Clause 6(a) is a **send** obligation only — no delivery-confirmation requirement, no auto-block clause. We nearly hard-coded a regulation that does not exist. Kept struck-through, not deleted, so the correction is auditable. Replaced by A5 (real timing invariant) + A34 (behavioural effect). |
| **A35** | Escalation response rate — no public source, carries the ₹ headline. Applied identically to every policy so it cannot manufacture lift. **Attack this first.** |
| **A36** | Failure-class mix. Was hardcoded in `harness.py` outside the freeze for six days; moved into config. Most impactful single parameter. |
| **A13** | Individual salary adherence is unknowable. This is the assumption the wasted-attempt regression *measures the cost of*. |
| **A26** | "Policy-agnostic" is a design property, NOT a benchmark against Razorpay's real engine — it exposes no callable interface. `external_policy_stub` makes this visible. |
| **A27** | Biggest interpretive gamble: that "measured money recovered" can be satisfied by simulated money, if labelled. |

A10/A13/A15/A17/A18/A22 are all the same failure in different clothes — a citable *aggregate*
stretched to cover a *per-individual* number no aggregate supplies. Unavoidable without real data;
that's why they're swept, not fixed.

---

## 9. What broke (build log — 20 entries, `docs/build_log.md`)

The most important artifact after the code. The strongest entries:

1. **#1** — Found Razorpay's Intelligent Retry Engine while fact-checking a citation. Reframed the
   whole project before writing code.
2. **#4** — Two days lost to a subscription-tokenization wall. The webhook log then *proved* it was a
   server-side failure in Razorpay's own test environment (`error_step: card_mandate_process`,
   `error_source: internal`) from their signed payloads. Pivoted to one-time payment links.
3. **#9** — First result was 89% recovery. Too good. Root cause: failure classes assigned
   independently of world state. Fix dropped it to 58.6% — made our own baseline *worse*.
4. **#10** — Compliance was logging violations and executing them anyway. Made it a veto.
5. **#13** — **The strawman baseline.** "Retry-friendly" meant the opposite of what was assumed. Cut
   the headline from ~36% to +11.8%.
6. **#14** — Sensitivity sweep returned byte-identical results for 3 scenarios → found two mechanisms
   doing *nothing* (congestion window never fired because all attempts were at midnight; revocation
   could only ever be a starting condition).
7. **#15** — Live LLM run: a truncated response was still perfectly *grounded*, passed validation, and
   silently dropped a required customer message. Guard now checks omission, not just invention.
8. **#16** — Predicted hedging would improve both metrics. It didn't. Mechanism measured: revocations
   doubled.
9. **#18** — The most impactful parameter was hiding outside the frozen config.
10. **#19** — The red team caught a **methodology error in our own scenarios** (we required in-range
    attacks while one of ours was out-of-range).
11. **#20** — Idempotency: a double-charge bug arriving through the most ordinary path in the system.

---

## 10. What is LEFT to do

### Required for submission
1. **Flip repo to public.** Safe — secret scan clean.
2. **Record the 5-minute video** (unlisted). Not scripted yet. Should show: the reproducibility
   command running, the HTML report, one live test-mode case, an audit-trail walkthrough, and the
   red team.
3. **Fill the 12-question form.** The question they read *first* is "What broke, and how you got
   out" — draw from build log #4, #13, #14, #19.

### Optional, genuinely valuable
- **Execute a real recovery action** — the policy schedules a retry and nothing ever fires it. In
  test mode a retry could genuinely be attempted. ~1h. Highest remaining demo value.
- **Subscription lifecycle** (`pending → halted`) — routed around due to the platform bug. Worth one
  more attempt. ~1h, may fail again.
- **Time-to-recovery as a swept first-class metric** — it's where hedged wins decisively and it isn't
  swept. ~45m.

### Known production gaps (documented honestly, NOT hidden)
- Durable state — everything is in-memory/per-run.
- Idempotency is in-memory and per-process (contract is right, persistence isn't).
- No scheduler — decisions emit timestamps; nothing fires them.

---

## 11. Working with this user

- **Prioritise execution over prep artifacts.** He corrected me once for proactively writing
  interview-prep material mid-build: *"the main goal of this project is problem solving skills."*
  Build; write prep only when asked or in the final polish window.
- **He wants to be challenged**, not agreed with. The whole project began as "try to destroy this."
- **He notices when I'm wrong** and says so directly. When it happens, fix it and move on — no
  grovelling.
- **Be honest about failures.** Every incident in the build log came from surfacing a problem, not
  hiding it. That discipline *is* the product.
- **Never paste secrets in chat.** He has done it once; don't encourage it.
- `docs/interview_prep.md` exists (gitignored) with all 100 VP-interview questions answered. It is
  prep, not submission material.

---

## 12. If you only remember five things

1. **The frozen config is sacred.** Change it only with a CHANGELOG entry stating whether results
   were already seen.
2. **Report the conservative number** (+12.5%), never the flattering one.
3. **Keep the metric we lose on.** It's why the rest is believable.
4. **The LLM never decides.** It narrates, attacks, and translates — always mechanically validated.
5. **The repo must be public before 5 September** or none of this is readable.
