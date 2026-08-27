# Build log — what broke and how we got out

Written as it happened, not reconstructed afterward. Each entry records the mistake honestly,
including the ones that were mine, and what the recovery actually demonstrates. Source material for
the submission form's "What broke, and how you got out" question and the pitch video.

Ordered chronologically. Newest entries appended at the bottom.

---

## 1. The project's core thesis was already shipped by Razorpay — found during fact-checking, not after submission

**What happened.** While verifying a retry-timing citation against Razorpay's live docs, the search
surfaced something unrelated to what I was checking: at FTX 2026, Razorpay had launched an
**Intelligent Retry Engine** (beta) whose own marketing critiques "rigid" retry systems that fire
"at fixed intervals without understanding user context, bank availability, or merchant priorities."
That is, almost verbatim, the thesis this project was built on. They also shipped a voice-led
**Subscription Recovery Agent** in Agent Studio. The track name itself — "AI Revenue Recovery" —
echoes their "Intelligent Revenue-Protect" branding.

**Why it mattered.** Submitting "we invented adaptive retry" to the company that shipped adaptive
retry six weeks earlier reads as either unaware or naive. Any judge on this track has seen the FTX
launch.

**How we got out.** Full reframe, before any code was written. Razorpay's own materials disclose
**no methodology, no rule-based-vs-ML answer, no recovery-rate or lift numbers, and no audit trail**
— it ships as a configurable black box. So the project became the thing that's missing: an open,
reproducible, auditable *evaluation harness* for adaptive retry policies, with the adaptive policy
as one example plugged into a policy-agnostic interface. That maps harder onto the track's own bar
(measured / batch / compliant escalation / stopping rules / audit trail) than the original framing did.

**What it demonstrates.** Competitive fact-checking before building, and the willingness to rewrite
the pitch rather than defend the first idea.

---

## 2. A "successful" page fetch that silently returned nothing

**What happened.** Fetching `razorpay.com/buildathon/` returned HTTP success and a page title — and
essentially no content. The page is JS-rendered. Nothing errored.

**Why it mattered.** I was one step from planning a 13-day schedule around a rubric I hadn't actually
read and a deadline I'd assumed. Opening it in a real browser revealed: **5 September deadline**
(not a generic two-week window), **students only**, submission is a public repo + unlisted 5-minute
video + a 12-question form, and four named judging criteria including *"AI judgment — the right tool
in the right place, and where you chose not to use one."*

**How we got out.** Re-fetched in a real browser, read the rendered DOM, pulled Track 03's brief
verbatim.

**What it demonstrates.** A tool returning 200 is not the same as a tool returning the truth. Verify
the content, not the status code.

---

## 3. Refusing to round an inference up to a fact (the T+1/T+2/T+3 citation)

**What happened.** The research brief carried a claim that Razorpay retries failed card subscriptions
on T+1, T+2, T+3, with source URLs carrying `utm_source=chatgpt.com` — i.e. routed through an LLM
web-search intermediary. Checked directly against the live docs: cards say only *"We automatically
retry the payment on the following day."* No multi-attempt cadence is published anywhere. The
UPI-specific "10 min → 1 hour → halt" schedule couldn't be confirmed either.

What *is* documented, precisely: Emandate's bank-holiday shift (charge on T-1, or T-3 if both T and
T-1 are holidays), and the 4-failed-attempts → `halted` rule.

**How we got out.** The retry cadence stays **A1 — the single highest Challenge Risk assumption in
the project**, explicitly labeled as having no public source, biased toward the most retry-friendly
plausible interval so any error makes the comparison *harder* on our own policy. The Emandate
holiday rule gets modeled exactly, as a FACT.

**What it demonstrates.** The difference between "we couldn't find it" and "it doesn't exist," and
building the evaluation so the unknown is swept rather than guessed.

---

## 4. Two days lost to a payment wall — and the log proved it wasn't our fault

**What happened.** Authenticating a test Subscription's card mandate failed repeatedly across a long
sequence of attempts:

- Razorpay's checkout recognized the real merchant identity ("Using as +91 97416…") and sent a
  **real OTP to a real phone** instead of using the test-mode mock flow.
- Chrome Incognito didn't fix it — Chrome syncs autofill identity into Incognito.
- Safari (zero Razorpay history) *did* fix the identity problem — but the OTP step then rejected
  every value tried, including properly random 6-digit ones.
- "Skip OTP" fell through to **"payment failed, please login."**
- Unchecking "Save this card as per RBI guidelines" was impossible — the checkbox re-enables itself,
  because subscriptions *require* a tokenized card for future debits.

**My own mistakes in here, recorded honestly.** I told the user to select **EMandate** and enter the
test UPI ID `success@razorpay`. That was wrong — EMandate is netbanking-based, not UPI, and no UPI
tab was even available on that checkout. I'd passed along a search summary without verifying it, and
got called on it. I also burned attempts driving the payment form with browser automation before
recognizing that a payment widget resisting scripted input is *correct behavior*, not a bug to route
around.

**How we got out.** Stepped back to the actual goal: the day's deliverable was *one real signed
webhook reaching our receiver* — not a subscription mandate specifically. Subscriptions mandatorily
tokenize the card (RBI CoFT), which is precisely the wall. A **one-time Payment Link** doesn't
tokenize anything, so it routes through the simple mock-bank Success/Failure page the docs describe.
Built `create_test_payment_link.py`, ran it, paid it — and got real `payment.authorized` and
`payment.captured` webhooks, signature-verified and logged.

**The part that turns this from an excuse into evidence.** The webhook log then showed that every
one of the failed subscription attempts *had* reached Razorpay's backend and fired real signed
webhooks — each carrying:

```
"error_step":   "card_mandate_process"
"error_reason": "server_error"
"error_source": "internal"
```

That's Razorpay's own cryptographically-signed data confirming the tokenization step was failing
**server-side inside their test environment**. The pivot wasn't a workaround for user error; it was
the correct response to a platform-side failure, and we can prove it. Separately, Razorpay's own
`subscriptions/test-guide` documents a simple *Pay → Success* flow with no OTP step at all — which no
longer matches current product behavior, most likely documentation lag behind tightened RBI CoFT
tokenization rules.

**What it demonstrates.** Knowing when to stop pushing on a blocked path, separating the goal from
the method, and using the system's own audit trail to establish *why* something failed rather than
guessing. Also: admitting a wrong instruction instead of quietly moving past it.

**Still open.** Full subscription-lifecycle authentication is deferred to Milestone 6, with time
budgeted to either resolve it or scope the live subset around one-time payments. Documented in
`integration/razorpay_test_mode/README.md`, not hidden.

---

## 5. A health check that answered — with the wrong service

**What happened.** Started the webhook receiver, curled `/health`, got `{"status":"ok","env":"development"}`.
That is not what our code returns. Our endpoint returns `{"status":"listening"}`.

**Why it mattered.** A pre-existing unrelated process was already bound to port 8000. Our server had
failed to bind (`errno 48, address already in use`) and exited — but the health check *passed*,
because something else was answering. Trusting it would have meant configuring Razorpay's webhook to
point at a tunnel connected to the wrong process, and debugging that from the far end.

**How we got out.** Caught it by noticing the response shape didn't match our own code, confirmed
with `lsof`, and moved to port 8010 — deliberately **not** killing an unknown process we didn't own.

**What it demonstrates.** Reading what a check actually returned, not just whether it returned.

---

## 6. Config fields that were tagged but empty

**What happened.** Day 3, while designing the six failure-class generators, three fields in the
already-frozen `sim_params.yaml` turned out to have `status: ASSUMPTION` tags and assumption IDs but
**no numeric values at all**: `bank_technical_decline.base_rate`, the `mandate_expired` validity
duration, and the amount type-mixture weights. Generator code can't run against a value that
doesn't exist.

**Why it mattered.** The project's central anti-circularity rule is that simulator ground truth is
frozen *before* any policy is evaluated against it — so touching the frozen config is exactly the
move that looks like cheating.

**How we got out.** Filled them in as new assumptions A31–A33, with a dated CHANGELOG entry in
`assumptions.md` stating plainly that the freeze commit **predates all policy and evaluation code**,
so no results existed to tune toward. Re-committed as the new frozen baseline with an updated hash.
The alternative — silently editing a frozen file — is the thing the whole discipline exists to prevent.

**What it demonstrates.** The freeze protocol working as a real constraint that costs something,
rather than as decoration. It's also enforced in code: `load_config()` raises if `meta.frozen` isn't
true or the hash is missing, with tests proving the check actually fires.

---

## 7. A CHANGELOG dated in the future

**What happened.** Routine schedule check compared `git log` against the `assumptions.md` CHANGELOG.
The commits were dated 2026-08-25; the CHANGELOG entries I'd written said 2026-08-26.

**Why it mattered.** Small, but in the one file whose entire purpose is auditable provenance. A
skeptical reviewer cross-referencing commit timestamps against the change record would find dates
that disagree — in the document that exists specifically to prove no parameter was changed after
seeing results.

**How we got out.** Corrected and committed with the reasoning in the commit message.

**What it demonstrates.** Auditability isn't a document you write once; it's a property you keep
checking. The check that caught this was routine, not triggered by suspicion.

---

## 8. The regulation didn't say what we'd been told it said

**What happened.** A load-bearing claim inherited from the research brief: *"RBI requires a
pre-debit notification; if undelivered, the debit is auto-blocked."* It had been carried as
assumption **A4** at MEDIUM confidence, verified only against press summaries, and it was driving
the design of both the `notification_undelivered` failure class and the compliance invariant.

Checked against the framework text before writing the policy interface. RBI's Digital Payments
E-mandate Framework 2026, **Clause 6(a)**, reads:

> "An issuer shall send a pre-transaction notification to the customer, at least 24 hours prior to
> the actual charge / debit."

That is a **send** obligation. There is no delivery-confirmation requirement anywhere in the
framework, and **no clause blocking a debit whose notification failed to arrive.** Confirmed against
two independent legal analyses of the framework text.

**Why it mattered.** We were one day from hard-coding a compliance invariant that enforced a rule the
regulator never wrote. "Our system blocks the debit because RBI requires it" invites exactly one
question from a judge who knows the framework — *which clause?* — and we had no answer.

**How we got out.** Split the refuted claim into the two real things underneath it:

- **A5 (upgraded to a quotable FACT):** the genuine hard constraint is on *timing* — no debit may be
  scheduled less than 24h after the notification was **sent**. This is now the compliance invariant,
  primary-sourced with a clause number, and it's a *better* invariant than the one we lost because
  it directly constrains retry scheduling, which is the thing this project actually measures.
- **A34 (new, honestly labeled ASSUMPTION):** non-delivery still degrades success, but
  **behaviourally** — an unaware customer is less likely to top up in time — not as a regulatory
  block. Modeled as a swept multiplier, never described as a compliance rule.

A4 stays in `assumptions.md` struck through and marked REFUTED rather than deleted, so the correction
itself is auditable. The test that asserted a hard block was rewritten to assert the opposite, with a
comment explaining that asserting `0.0` would encode a regulation that doesn't exist.

**What it demonstrates.** Checking the primary source instead of the summary of the summary — and
finding that the honest version of a claim can be more useful than the overstated one. This is the
single most consequential correction in the project so far.

---

## 9. The first number was too good, and the reason was a modelling bug

**What happened.** The first baseline run reported **89.0%** recovery on recoverable mandates, with
**zero** wasted attempts and every single recovery landing in exactly 1.0 days (IQR 1.0–1.0).

**Why it mattered.** An 89% baseline is both implausible and strategically bad — if the naive policy
already recovers nine in ten, there is almost no headroom for an adaptive policy to demonstrate
anything, and any lift we did report would look manufactured. A suspiciously good number for your own
*baseline* is worth more scrutiny than a bad one, because it's the direction that doesn't flatter you
and therefore doesn't trip your own defences.

**Root cause.** The harness assigned each mandate a failure class *independently* of the simulated
balance trajectory. So a mandate could be labelled an `insufficient_funds` failure on a day when its
balance comfortably covered the amount — an incoherent world state. Those mandates then "recovered"
trivially on the next-day retry, because nothing had ever actually been wrong.

**How we got out.** Failure days are now anchored to a day on which the assigned failure class is
genuinely true: insufficient-funds failures occur on a day the balance is actually short, expiry
failures occur at or after expiry, and so on. Baseline recovery fell to **58.6%** across 30 seeds,
wasted attempts became non-zero, and the simulation became internally consistent.

Worth stating plainly: this is a *correctness* fix, not tuning. No adaptive policy existed at the
time — there was no result to tune toward, and the change made our own baseline look **worse**, not
better.

**What it demonstrates.** Interrogating a result that favours you. The bug was only findable by
asking "why is this number good?" rather than banking it.

---

## 10. A compliance check that logged violations and let them through

**What happened.** The same first run reported **183 compliance violations** — and completed every
one of those retries anyway. The invariant module was recording verdicts that nothing acted on.

**Why it mattered.** The whole pitch is auditable, compliant recovery. A compliance floor that gets
written to a log and then ignored is theatre: it produces the *appearance* of governance with none of
the effect. A judge reading the audit trail would find our own system documenting its own violations.

**Diagnosis.** The violations were real and correctly detected: 128 of 500 mandates exceeded the
₹15,000 no-OTP ceiling (RBI A6), because the SIP and EMI amount bands run to ₹25,000 and ₹50,000.
Above that ceiling a recurring debit legally requires additional factor authentication, so it cannot
be silently auto-retried — it needs customer re-authentication, which is an *escalation*, not a retry.

**How we got out.** Compliance became a **veto**: the harness refuses to execute a non-compliant
retry regardless of what the policy asked for. The proposal is still recorded, now as
`blocked_by_compliance` with the failing invariant attached, so a policy that repeatedly proposes
illegal actions is visible in the audit trail rather than quietly corrected behind the scenes.

**The strategic consequence.** Across 30 seeds, the baseline proposes a non-compliant auto-retry on
**25.2%** of mandates — and loses all of that value, because a blocked retry recovers nothing. That
is not a bug in the baseline; it is precisely what "rigid, context-blind retry" *means*, and it is a
measurable, compliance-grounded opening for the adaptive policy to exploit by escalating to
re-authentication instead of blindly retrying. The rubric's "compliant escalation" clause stopped
being a box to tick and became a source of measurable recovery.

**What it demonstrates.** Enforcement over documentation, and noticing that a component which
*reports* correctly can still be *wired* wrongly.

---

## 11. The adaptive policy lost on one of its own headline metrics

**What happened.** First three-way run. The adaptive policy beat baseline on recovery
(58.6% → 79.9% on recoverable mandates) and on money (₹10.3M → ₹21.4M). It also **wasted three times
more attempts proportionally** — 0.8% → 2.3%, a **+202%** regression on a metric the project's own
brief names as a goal ("reduce wasted retries").

**Why it mattered.** The temptation was obvious: quietly drop wasted attempts from the headline, or
tune the policy until the number went green. Both would have been the exact failure this project
exists to avoid — the metric was defined and frozen (ε = 0.01) on Day 4, *before* any adaptive policy
existed, specifically so it couldn't be redefined once it became inconvenient.

**Diagnosis.** A per-failure-class breakdown put all the extra waste in one place:

| failure class | baseline | adaptive |
|---|---|---|
| `insufficient_funds` | 1.1% wasted | **3.4% wasted** |
| everything else | 0.0% | 0.0% |

The cause is the population-level salary bet itself. The adaptive policy waits for the next likely
income event (1st / 7th / month-end) instead of retrying next day. For customers who follow that
pattern, it wins. For the substantial minority who don't — irregular and informal earners, weighted
at 20–40% of the population in the frozen config — it waits ~30 days and then attempts against a
genuinely empty account. Baseline's next-day retry also fails for those customers, but against a
*marginally* funded account, which scores above the waste threshold.

So the adaptive policy converts near-miss failures into confident misses. **That is not a bug; it is
the measurable cost of A13** — the assumption, flagged HIGH risk on day one, that population-level
salary clustering says nothing about whether *this* customer follows it.

**How we got out.** We reported it. The trade-off is real and it is the interesting result: the
policy buys a large recovery gain by concentrating attempts on moments it believes are good, and pays
for it in attempts spent on the customers it is wrong about. Whether that trade is worth making is a
business question — it depends on what an attempt costs — and the harness's job is to surface the
trade honestly, not to collapse it into a single flattering number.

**What it demonstrates.** A metric defined before the result, and honoured after it. An evaluation
harness that only ever flatters its own reference policy is not a harness, and the most credible
number in a bake-off is usually the one that went the wrong way.

---

## 12. The policy could have read the answer sheet

**What happened.** While investigating entry 11, a look at what the policy actually receives at
decision time turned up a structural leak: `PolicyState` carried the full `Mandate` object — and
`Mandate` carries `income_timing_type`, the customer's *actual* salary-cycle pattern.

**Why it mattered.** That field is simulator ground truth about an individual. A13 states plainly
that no public source can tell you whether a given customer is paid on the 7th; the entire
non-circularity argument rests on the policy making a *population-level* bet and being wrong for the
people who don't fit it. A policy that read `income_timing_type` would be scheduling retries against
the answer sheet, and every lift number in the project would be worthless.

The adaptive policy did **not** read it. But "we checked and it doesn't" is not a guarantee a
reviewer can verify without reading every line of every policy, forever, including ones added later.

**How we got out.** Made it structurally impossible rather than merely true. Policies now receive
`MandateView` — a redacted projection carrying id, amount, amount type, creation date and validity,
and nothing else. `income_timing_type` is not a field on the type, so no policy can read it, by
accident or otherwise. A test asserts the field's absence on the view and its presence on the full
simulator-side object.

**What it demonstrates.** The difference between a guarantee that holds and a guarantee you can
*prove* holds. Non-circularity claims are worth exactly as much as their enforcement mechanism —
"we were careful" is not an enforcement mechanism.

---

## 13. Our baseline was a strawman, and we'd built it on purpose without realising

**What happened.** The project brief was explicit: *"design the baseline conservatively (i.e. bias
toward the most retry-friendly plausible interval) so any error favors the harder comparison case,
not the easier one."* We implemented that as cadence `[1]` — retry the next day, every time — reading
"retry-friendly" as "retries eagerly." It also matched the one documented fact: *"We automatically
retry the payment on the following day."*

Before building the sensitivity sweep, a quick check of what the baseline actually scores under
different cadences:

| assumed cadence | baseline recovery |
|---|---|
| `[1]` — next day, every time | **63.5%** |
| `[1, 2, 3]` | 68.2% |
| `[1, 3, 7]` | 71.5% |
| `[7, 7, 7]` | 73.7% |
| `[3, 7, 14]` — spread backoff | **74.6%** |

**Why it mattered.** `[1]` is the *weakest* plausible fixed schedule, by eleven points. In a world
dominated by insufficient funds, retrying tomorrow hammers an account that is still empty; spreading
attempts out catches the next income event by accident. So "retry-friendly" was exactly backwards —
we had built the most flattering possible comparison and called it conservative. Every lift number to
that point was inflated, and a judge who ran this same check would have found it in five minutes.

**How we got out.** Baseline cadence became a swept dimension with five plausible schedules, and the
**headline is now reported against the strongest baseline we could construct**, not the documented
one. That single change cut the recovery-rate lift from roughly **+36% to +11.8%**.

The documented `[1]` reading is still reported — it is the only cadence with any public evidence
behind it — but it is presented as the *optimistic* end of a range, never as the claim.

**What it demonstrates.** Checking whether your own control condition is fair, and preferring the
number that survives the hardest version of the comparison. A +11.8% lift you can defend is worth
more than a +36% lift that dissolves under one question.

---

## 14. The sweep found two dead mechanisms by returning identical answers

**What happened.** First full sensitivity run, 15 scenarios. Three of them —
`severe_congestion`, `mild_congestion`, and `early_revocation` — returned results **byte-identical**
to the reference case. Overrides that should have moved outcomes moved nothing.

**Diagnosis, bug 1 — the congestion window never existed.** Mandates were created at midnight, and
every retry inherited that time-of-day. NPCI's documented deprioritisation window is 10:00–13:00, so
**no attempt in the entire simulation ever fell inside it.** The `npci_congestion` failure class was
inert, and the adaptive policy's congestion-avoidance rule (ADAPT-005) had been contributing exactly
zero while appearing to work — a rule that passed its unit test, ran in production, and did nothing.

**Diagnosis, bug 2 — customers could never give up.** `mandate_revoked` only ever appeared as a
*starting* condition, which both policies immediately stopped on. So A16's revocation threshold was
never read by anything, and the "customer revokes after repeated failures" dynamic — the single
mechanism that makes wasting attempts genuinely costly, and the one grounded in the ~20M monthly UPI
Autopay revocations — was absent from the model entirely.

**How we got out.** Failure times are now consistent with their cause (a congestion failure happens
*during* the congestion window, other classes spread across plausible processing hours), and a
customer can now revoke mid-sequence once consecutive failures exceed their patience threshold,
converting a recoverable mandate into a permanent loss.

**The part that deserves scrutiny.** Both fixes **increased** our own measured lift (median
+26.7% → +36.1%), which is the direction that should never be accepted without justification. The
honest accounting:

- Congestion now hurts the baseline because the baseline retries at the same time of day and lands
  back in the window, while the adaptive policy shifts to a documented better window. That is the
  rule doing the job it was written to do — and it was previously credited with nothing.
- Revocation now punishes any policy that burns attempts, which is a cost the model was simply
  missing.

Neither mechanism was invented to help; both were already declared assumptions (A7, A16) that turned
out not to be wired to anything. But because they flatter us, the conservative headline — **+11.8%
against the strongest baseline** — remains the number we quote, not the median.

**What it demonstrates.** The sweep paying for itself immediately: not by confirming the result, but
by exposing two mechanisms that were silently doing nothing. A scenario that changes an input and
produces an identical output is not a passing test — it is a bug report.

---

## 15. The hallucination guard passed a broken narration, because it was watching the wrong failure

**What happened.** First run of the narrator against the real Claude API rather than a stub. Five of
six records came back clean and passed grounding validation. The sixth ended like this:

> "…Compliance checks INV-RBI-6a-NOTIFICATION-TIMING and INV-RBI-O"

Cut off mid-identifier. And its customer message — an escalation for a ₹26,287 debit above the
₹15,000 OTP ceiling, which *requires* contacting the customer to re-authenticate — came back empty.

**Why the guard missed it.** The response hit `max_tokens` and was truncated. But a truncated
response is still perfectly **grounded**: every number in it came from the record, the rule ID was
cited, no prohibited claims appeared. The validator was built to catch *invention* and had nothing to
say about *omission*. It passed the record, and the truncation silently converted "tell the customer
to re-authenticate" into "say nothing to the customer."

In a real deployment that is a dropped regulatory obligation, produced by a validator reporting
success.

**How we got out.** Two additions:

- **Truncation check** — `stop_reason == "max_tokens"` rejects the response outright and falls back
  to the template. Root cause, handled at the source.
- **Completeness check** — if the decision record calls for customer contact, a narration with no
  customer message is rejected. Silence where an obligation exists is not a valid narration.

Both are regression-tested, including a fake that reproduces the exact truncated string observed.

**What it demonstrates.** The most useful thing the live model did was fail in a way the stub never
could. Every guard encodes an assumption about *how* the thing you're guarding will go wrong — ours
assumed the model would say too much, and it said too little. That the fallback then produced a
correct, complete narration is the layered design working exactly as intended: the LLM failed, and
the system did not.

---

## 16. The fix for the wasted-attempt problem made recovery worse, for a reason we could measure

**What happened.** The adaptive policy beat baseline everywhere except wasted attempts, where it was
worse in 13 of 15 scenarios (entry 11). The obvious fix: stop committing the entire 4-attempt budget
to one bet. Probe early and cheaply on attempt 1, keep the income-event wait for attempts 2+.

Predicted outcome: keep most of the recovery gain, cut the waste. What actually happened, across 30
seeds:

| | adaptive | adaptive_hedged |
|---|---|---|
| recovery rate (recoverable) | **77.8%** | 74.3% |
| value recovered | **₹20.3M** | ₹19.7M |
| wasted attempt rate | 1.9% | **1.6%** |
| median days to recovery | 3.5 | **1.0** |

Recovery went **down**. The prediction was wrong.

**Why — and this is the useful part.** Counting mid-sequence revocations across both policies:

| | mid-sequence revocations |
|---|---|
| adaptive | 99 (3.3% of mandates) |
| adaptive_hedged | **214 (7.1% of mandates)** |

The extra probe spends a unit of customer patience. A16 says customers revoke after 2–4 consecutive
failed debits; an early attempt that fails pushes threshold-2 customers into revoking **before the
income-event bet ever gets played**. The hedge more than doubles permanent, customer-initiated
losses in exchange for lower waste. That mechanism was invisible until the model actually had it —
it only exists because entry 14 wired up revocation, which had previously been dead.

**Across the full sweep**, the trade is consistent:

| | median rate lift | median value lift | median waste lift | conservative rate lift |
|---|---|---|---|---|
| adaptive | **+36.1%** | **+112.2%** | +79.5% | **+11.8%** |
| adaptive_hedged | +27.2% | +106.2% | **+40.4%** | +7.7% |

Hedging roughly halves the waste regression and cuts median time-to-recovery from 3.5 days to 1.0,
at a cost of about nine points of recovery lift. Both stay positive on rate and value in 15/15
scenarios. **Neither policy dominates.**

**How we got out.** We didn't pick a winner. Both policies ship, both are reported, and the
trade-off is the finding: *maximise recovery, or recover faster and waste less — these are different
policies and the harness prices the difference.*

That is also the sharpest version of this project's pitch. Razorpay's Intelligent Retry Engine
invites merchants to "configure their own retry strategies" and "define retry cadence"; it publishes
nothing about what any given configuration costs. Here the cost is measured, decomposed, and
attributable to a named mechanism.

**What it demonstrates.** A prediction that was wrong, caught by measurement rather than argument,
with the mechanism identified instead of hand-waved. The change is logged in `assumptions.md` as
policy iteration after seeing results — the simulator config was untouched, because the freeze
protects ground truth, not the thing being engineered against it.

---

## 17. The live batch couldn't be what the plan said it would be

**What happened.** M6 was planned as "a scripted ~15–20 case live test-mode batch." Building it
surfaced that this is not achievable on a standard test account:

- Completing a payment requires Razorpay's hosted checkout, which needs a human and actively
  resists automation (entry 4).
- Razorpay's **server-to-server API**, which would allow programmatic payment creation, requires
  contacting their support team to enable. Not available on a fresh account.
- There is **no test-mode payment-simulation endpoint**. The dashboard's "Charge this now" control
  is UI-only and applies to subscriptions, which is the path that fails server-side.

So "20 scripted completed payments" was never possible, and no amount of effort would have made it so.

**How we got out — by asking what the milestone was actually for.** Its purpose (A30) was never a
statistically powered sample; it was evidence that the system talks to real Razorpay APIs end to end.
That does not require 20 completed *payments*. It requires the real policy engine operating on real
entities, through the real API, into the real audit schema. So the batch became:

1. create a payment link via the real API,
2. re-fetch it via the real API (round-trip, not fire-and-forget),
3. map a **documented Razorpay decline code** onto our failure taxonomy,
4. run the actual `AdaptivePolicy` on it,
5. run the actual compliance invariants,
6. write a `DecisionRecord` tagged `source: live_test_mode`.

The policy cannot tell a real entity from a simulated one — that is what the `MandateView` boundary
buys. Result: **9 real entities, 9 policy decisions, 1 compliant escalation (a ₹41,000 case correctly
routed to re-authentication rather than a retry that would be refused), 0 compliance violations.**

**A second constraint found by running it.** The first attempt died on
`BadRequestError: Too many requests` after five entities — Razorpay rate-limits test-mode writes.
Fixed with inter-call pacing and exponential backoff that *degrades* the batch rather than aborting
it, so a rate limit costs a few cases instead of discarding every decision already recorded. The run
log shows it backing off, skipping three cases, and recovering. Handling this is part of what "the
integration works" means, not an inconvenience around it.

**A third thing, found by a test.** The decline-code mapping originally listed `server_error`
alongside Razorpay's documented codes. A test asserting "every mapped code has a test card" failed on
it — correctly. `server_error` is real (it appeared in every signed webhook from the Day 2
tokenisation failures) but Razorpay publishes no card that triggers it on demand. Those are different
grades of evidence, so the mapping now separates `DOCUMENTED_ERROR_REASONS` (triggerable, verifiable)
from `OBSERVED_ERROR_REASONS` (seen in real traffic, not reproducible), and a test enforces the split.

**What it demonstrates.** Separating a milestone's stated form from its actual purpose, and being
explicit that the count is 9 rather than 20 because of a platform limit — not quietly reporting 9 as
though it were the plan. The live batch was never going to carry a statistical claim, so losing
eleven cases to a rate limit costs nothing except the appearance of a rounder number.

---

## 18. The most impactful parameter in the simulator was hiding outside the frozen config

**What happened.** Reviewing the project for weak points before writing it up, a check for
ground-truth values living outside `config/sim_params.yaml` found one: `FAILURE_CLASS_WEIGHTS` — 55%
insufficient funds, 15% congestion, and so on — hardcoded in `eval/harness.py` since day 4.

**Why it mattered.** That is the distribution determining what the policy is even optimising for. It
was the single most impactful parameter in the simulator, it carried no assumption ID, it could not
be swept, and it sat **outside the freeze protocol on which the project's entire credibility claim
rests.** Every sentence written about frozen ground truth was, strictly, false about the most
important number in it. A reviewer would have found this in minutes and been right to discount
everything around it.

**How we got out.** Moved to the frozen config as **A36**, values unchanged so no result moved, with
a CHANGELOG entry. Then, because it was finally sweepable, three failure-mix scenarios were added —
funds-dominated, technical-dominated, high-unrecoverable — taking the sweep from 15 to 18. All still
positive. `technical_dominated_mix` turned out to be a *third* scenario where adaptive actually
improves wasted attempts (−41.8%), because transient declines suit its quick-retry rule rather than
the long salary wait.

**What it demonstrates.** That a discipline is only as good as its coverage, and that the gap will be
in the thing you wrote earliest and stopped looking at. Nothing about the freeze protocol was wrong —
it just had a hole in it, in the highest-leverage place, for six days.

---

## 19. We pointed the model at our own results and told it to break them

**What happened.** Every other use of an LLM in a payment-recovery system points the same way: the
model advocates an action, a human hopes it was right. We pointed it the other way. `eval/redteam.py`
hands Claude the assumption table and the frozen config and asks it to find parameterisations where
the adaptive policy **loses**.

The safety argument is the same one used everywhere else in this project. Nothing the model says is
trusted: every proposed scenario is mechanically validated against the schema and the ranges already
declared in `sim_params.yaml`, surviving scenarios execute through the same sweep machinery as the
hand-written ones, and the verdict comes from the metrics. The model can hallucinate and the worst
case is a wasted scenario, never a false result.

**Result across 16 generated attacks: none landed.** But the interesting number is the weakest lift —
**+5.7%**, against a floor of +10.0% across all 18 scenarios we had written ourselves. *The model
found harder attacks than we did.* The three hardest were all **interaction effects**, which is
precisely the blind spot it identified in us:

> "The sweep tested mild_congestion and stable_balances separately; the interaction is where the lift
> should vanish."

That is what a good reviewer says, and we had not thought of it.

**And it caught a real methodology error in our own work.** One proposal came with this note:

> "their `mostly_irregular_income` scenario pushed the irregular weight to 0.70, which is OUTSIDE the
> declared [0.2, 0.4] range — so the honest in-range version of that attack has never been combined
> with the strongest baseline."

Correct. We had imposed "stay inside declared ranges" on the model while one of our own scenarios
broke that rule. It breaks it in the direction that is *harder* on us, so it was never self-serving —
but it was inconsistent, and it meant the honest in-range version of that attack was untested. The
scenario is now labelled `mostly_irregular_income_out_of_range` and kept as an extreme stress test,
with the in-range version added beside it (+12.2% against the strongest baseline). The sweep is now
19 scenarios.

**Two bugs found in the process.** The first live run truncated at `max_tokens`, so the closing code
fence never arrived and a paired-fence regex returned unparseable text — the same failure family as
entry 15, and a reminder that a guard written for *wrong* output still has to cope with output that
stops early. The second: two proposals were rejected for indexing into a list
(`types[0].weight_range`), which the override mechanism doesn't support. The fix was to include the
existing scenarios in the prompt as worked examples, after which 10 of 10 proposals validated.

**What it demonstrates.** A use of a language model that strengthens the rigour of a result instead of
substituting for it — and a red team that earned its keep on the first run, not by confirming the
result, but by finding a harder attack than we had and an inconsistency in our own method.

---

## 20. The double-charge bug we hadn't written yet

**What happened.** While writing up the project's production gaps, one had to be listed as *not
implemented*: idempotency. Razorpay retries webhooks that don't return 2xx, and networks duplicate
deliveries independently of that. The live loop had no deduplication, so the same `payment.failed`
arriving twice would increment the attempt counter twice and produce two decisions.

**Why it mattered.** In this repo that's a cosmetic double-entry in a log. In any deployment where a
decision actually fires a debit, it is a **double charge against a customer for a single failure** —
and it would arrive through the most ordinary path in the system, a webhook retry, not through
anything exotic.

**How we got out.** Deduplication keyed on the *event*, not the delivery: `(event type, payment id)`.
The key deliberately excludes timestamps and delivery identifiers, both of which vary between retries
of the same event — include them and every redelivery looks new, so the deduplication silently does
nothing while appearing to work. There's a test pinning exactly that.

A replay returns the **original decision** rather than nothing. Silently dropping it would leave the
caller with no answer for an event it legitimately asked about; returning the first decision is both
idempotent and honest — the same question gets the same answer.

Verified over real HTTP: three deliveries of one event → **1 decision recorded, 2 deduplicated**, with
the replays returning an identical rule ID and retry timestamp.

**What it's still not.** In-memory and per-process. In production this belongs in a durable store
keyed on the same identity, with the decision log as the source of truth. The module says so in its
own docstring rather than implying a persistence guarantee it doesn't have — an idempotency store
that quietly loses state on restart provides weaker guarantees than its callers assume, and the place
to be clear about that is in the code, not in a postmortem.

**What it demonstrates.** Auditing your own work for what you'd have to admit under questioning, and
then removing the admission. The gap was found by writing an honest list of weaknesses, which is a
reasonable argument for writing one.

---

## 21. Every policy comparison had been drawing from two different worlds

**What happened.** Building the oracle needed a clean per-failure-class breakdown, comparing adaptive
against a policy with perfect information. A quick diagnostic script produced a strange result:
totals per failure class differed noticeably between the adaptive run and the oracle run of the "same"
seed. Checking directly: **30 of 50 mandates got assigned a different failure class** between a
baseline run and an adaptive run of the identical seed.

**Root cause.** `run_policy_on_batch` seeded one RNG at the top of the function and let it advance
continuously across the whole batch loop. Mandate *generation* (amount, type, timing) came from a
separate, genuinely policy-independent process, so that part was always fair. But failure-class
assignment, balance-trajectory generation, and every attempt-loop draw came from that one shared,
continuously-advancing stream — and because different policies take different numbers of attempts,
they consume a different number of draws per mandate. The instant policy A and policy B diverged on
mandate 1's attempt count, mandate 2 onward started drawing from different points in the stream under
each policy. "Mandate 47" was not the same synthetic entity across two policy runs; it was two
different mandates that happened to share an index.

**Why it mattered, and why it didn't invalidate anything already reported.** Aggregate comparisons —
56.9% vs 78.0% recovery — stayed statistically valid; both figures are large-N averages over
independent samples from the same generative process, and the law of large numbers doesn't care
whether the samples are paired. But "the same batch of mandates," read literally, hadn't been true.
A matched-pairs design — mandate 47 faces the identical failure cause and balance curve under every
policy, only the chosen timing differs — is strictly more rigorous: same validity, lower variance, and
a much more auditable claim ("only the timing choice differed" beats "these were independently drawn
and averaged out"). It's also the property the oracle comparison benefits from most, since the whole
point was to show precisely *where* it wins.

**How we got out.** Each mandate now gets its own RNG, seeded by `(seed, mandate_index)`, independent
of every other mandate's draw consumption. World-generation (failure class, trajectory) happens first
within that per-mandate stream, before any policy sees the mandate, so it's provably identical
regardless of which policy runs next. Verified directly: 0 mismatches across all 200 mandates for
baseline vs. adaptive vs. oracle, same seed, where the un-fixed version had produced 30/50 mismatches
on a smaller sample. Two regression tests pin this — one checking cross-policy agreement directly, one
checking that a later mandate is unaffected by how many attempts an earlier mandate consumed under a
different policy.

Per-attempt realized randomness (notification-delivery luck, decline-magnitude draws) is deliberately
**not** re-matched beyond this. Those depend on which day and attempt number a policy actually chose;
asking "what would the coin flip have been on a day this policy never attempted" isn't a more rigorous
question, it's a different one. Matching stops exactly at "what world does this mandate start in" —
the same boundary the `MandateView` redaction already draws between world and policy.

Every canonical number in this project was regenerated after this fix. The direction and shape of
every finding held; the conservative headline moved from +11.2% to +12.5%, tighter rather than
different, consistent with a lower-variance design producing a cleaner estimate rather than a new
conclusion.

**What it demonstrates.** A subtle correctness property, found not by looking for it but by building
something new (the oracle) that made an existing blind spot visible for the first time. The fix was
small — one line, reseed per mandate instead of once per batch — but it was foundational: it touched
every comparison the project had ever made, and every one of them got more rigorous, not different.

---

## 22. An oracle that could only win where the theory said it could

**What happened.** The project's own architecture review identified a real weakness: enormous
evaluation machinery pointed at one modest deterministic policy, with no way to say whether 78%
recovery was actually *good* — good relative to what? A weak baseline, a strong one, the best
achievable? Rather than adding a predictive model (rejected on separate grounds — trained and
evaluated on the same synthetic simulator whose assumptions the project spends 6,000 words
documenting as unverified, which trades "we don't have this" for a strictly worse claim: "we predicted
our own assumptions back to ourselves"), the fix was an **oracle**: a policy allowed to see the
customer's true balance trajectory, used only to establish a ceiling, never registered as a
deployable candidate.

**The design discipline that made it defensible rather than a cheat.** Before writing any code, every
success-probability function in the simulator was traced by hand. The result was narrower than
expected: day-of-attempt timing only changes ground-truth probability for **two** of six failure
classes — `insufficient_funds` (via the balance curve) and `npci_congestion` (via the hour-of-day
window, and that one's already fully solved by the existing congestion-avoidance rule once the retry
hour is fixed outside the bad window). For the other four classes, probability is either
day-independent or a hard stop regardless of timing. So the oracle isn't a new policy built from
scratch — it *is* the adaptive policy, with exactly the one guess (population-level payday) replaced
by the true answer, and every other branch inherited unchanged, including the 4-attempt cap and the
OTP-ceiling escalation. If it won everywhere, that would mean the analysis was wrong. It didn't:
oracle matched adaptive exactly on `bank_technical_decline` (80.8% both) and `notification_undelivered`
(81.4% vs 81.5%, noise), and beat it specifically on `insufficient_funds`.

**Result:** adaptive captures **95.2%** of the oracle's recovery rate. Oracle's own wasted-attempt
rate: **0.0%** — it only ever retries on a day it already knows will work, which is exactly the
information a real policy doesn't have and structurally can't.

**The two things that had to be scoped precisely, or the claim would overreach.** First: the oracle is
a *recovery-maximising* ceiling specifically, not a simultaneous ceiling on every metric — the
sequence that maximises recovery probability isn't necessarily the one that minimises waste or
time-to-recovery, and the report says so rather than implying one oracle bounds everything at once.
Second: the oracle sees the balance trajectory and nothing else — not the customer's private
revocation threshold, not which random draw a technical decline or notification-delivery event will
land on. Extending its knowledge indefinitely would make "oracle" meaningless; this is bounded,
specific foreknowledge about the one thing that actually matters, not an exemption from the rules
everyone else follows.

**How the leak stays contained.** `MandateView` still structurally omits the trajectory from every
other policy. The oracle gets it through `observe_trajectory`, a hook that isn't part of the `Policy`
contract — only `OraclePolicy` implements it, the harness calls it via `hasattr` and stays completely
policy-agnostic otherwise, and every other policy's ignorance of the true balance curve remains
exactly as structural as it was before the oracle existed.

**What it demonstrates.** A standard technique from other fields (perfect-information optimum,
oracle forecast, expert policy) applied with the same discipline as everything else here: define the
ceiling's exact scope before measuring against it, verify by hand that the mechanism producing the
result matches the mechanism claimed, and report where it *doesn't* win as carefully as where it does.

---

## 23. The tokenization wall, retried on purpose — and it held

**What happened.** Two days after entry 4's original failure, deliberately retried the exact same
subscription-authorization path once: fresh subscription, Safari (no saved identity), the same
documented test card. The reasoning for trying again: the original failure was platform-side
(`error_source: internal`), so it was plausibly a transient issue Razorpay had since fixed, and
finding out costs little if the attempt is bounded.

It wasn't fixed. Same wall.

**The part worth recording is the discipline, not the outcome.** The protocol was agreed *before*
attempting: one clean try, Safari, the documented card, and a hard stop the moment the same failure
mode reappeared — no browser-switching, no "one more thing to check," no repeat of the multi-hour
troubleshooting entry 4 describes. It held. First sign of the familiar failure, the attempt stopped,
and this entry got written instead of another hour of debugging.

**Why a second failure is better evidence than the first alone.** One occurrence could plausibly be
a fluke — a bad deploy that happened to be live for a few hours on one specific day. Two occurrences,
in separate sessions, on different dates, following the exact same steps, is the signature of a
persistent issue rather than a coincidence. The live-batch fallback (`create_test_payment_link.py`,
entry 4/17) is confirmed as the right call, not a workaround abandoned early — full subscription
lifecycle demonstration stays out of scope for this submission on that basis, not on time pressure.

**A small, real bug fixed in passing.** Creating a fresh subscription for the retry hit an unrelated
issue: `client.customer.create(..., fail_existing=0)` was supposed to reuse an existing test customer
rather than error, and didn't. Fixed by generating a unique email per run instead of chasing the SDK's
exact expected serialization for that flag — simpler, and just as correct for a throwaway test
customer that only exists to exercise the API.

**What it demonstrates.** That "try it again" and "keep debugging indefinitely" are different
decisions, and the value of retrying a known failure comes entirely from bounding it in advance. An
unbounded retry would have cost hours for the same answer; a bounded one cost ten minutes and
produced stronger evidence than doing nothing.

## 24. Asked "are we vulnerable in any way" and checked, instead of answering from memory

**What happened.** Went through HANDOFF.md's own "things that will destroy this project" list — the
frozen config, the `MandateView` redaction wall, the frozen ε, headline-number consistency, the
simulated/live separation, and the no-LLM-in-the-loop rule — one by one, against the actual current
repo state rather than against what the docs claimed.

**Found a real one.** `config/sim_params.yaml`'s `frozen_commit_hash` pointed at
`8e2d9a49d5e3cbea10f461e67059dc9e79f94638`, a commit that *predates* `5e2eb70` (entry 18's A36 move,
which put `failure_class_mix` inside the frozen config). Every prior post-freeze change — A4, A35 —
got a proper "rebaseline the hash" follow-up commit. A36 didn't. The freeze claim and the file's real
history had quietly diverged, and nothing would have caught it: `simulator/config_loader.py` only
checks that the hash field is a non-empty string, never that it points at matching content. This is
exactly the failure mode the "freeze is decoration, not a guarantee" warning describes — it just
hadn't happened yet when that warning was written.

**Fixed and, more importantly, guarded.** Rebaselined the hash to the commit whose snapshot actually
matches current content, and added `tests/test_frozen_config_integrity.py`, which runs `git show
<hash>:config/sim_params.yaml` and diffs it against the file on disk (normalising out only the
self-referential hash line). Verified it actually discriminates: red against the old broken hash,
green against the corrected one. This is now a permanent regression test, not a one-time fix — the
next silent hash-drift, whenever it happens, fails the suite instead of sitting undetected.

**The headline-number sweep.** Grepped every tracked `.md`/`.py` file for old percentage figures
(`11.2%`, `11.8%`, `81.1%`, `58.4%`, etc.) to check invariant 3.4. Two different things came back:

- `docs/build_log.md` and `assumptions.md` carry old figures inside *dated, past-tense* entries —
  e.g. entry 13's "+36% to +11.8%", CHANGELOG's "+11.8%". These describe what was true *when that
  entry was written*, the same way this entry's own numbers will read as history someday. Rewriting
  them to the current figure would falsify the log, not fix it — left alone, same as entry 21's "moved
  from +11.2% to +12.5%" is correctly left alone.
- `HANDOFF.md` is a current-state snapshot, not a log — every occurrence there was genuinely stale
  (`+11.2%` instead of `+12.5%`, a `19/19` range of `+10.3% to +58.4%` instead of `+10.3% to +54.7%`,
  a `16 AI-generated attacks / weakest +5.7%` redteam claim from an earlier, smaller-sweep run, plus a
  "quick facts" table with a stale commit count, file count, line count, and — the same bug as
  above — the stale frozen-config hash). Regenerated the actual current numbers by rerunning
  `eval/run_eval.py` (30 seeds × 200 mandates) and `eval/sensitivity.py` rather than hand-editing
  guesses, and rewrote every figure in HANDOFF.md's results section, quick-facts table, and "five
  things to remember" list to match.

**One number got weaker, not stronger, and that's reported too.** The current 5-attack redteam run's
weakest result (+10.8%) is *not* below the current hand-written sensitivity floor (+10.3%) the way
HANDOFF.md's old text claimed ("below the +10.0% floor of every hand-written scenario") — it's barely
above it. Rather than re-running the (paid, LLM-backed) redteam until a scarier number reappeared,
which would be exactly the kind of result-shopping this project's whole methodology exists to refuse,
the honest current figure is reported as-is, with a note that redteam output isn't deterministic
between runs and the number should be re-verified, not copied, before the video or form.

**Also checked, held clean:** `MandateView` still structurally excludes `income_timing_type` from
every policy (3.2); `wasted_attempt_epsilon` is still 0.01, untouched since before any policy existed
(3.3); no `source: live_test_mode` figure is ever combined with a `source: simulation` one anywhere in
`eval/report.py` — the live samples section renders raw qualitative records, not a computed lift, so
there is no numeric path by which they could merge (3.5); no `policies/*/policy.py`, `compliance/`, or
`eval/harness.py` code path lets an LLM call influence a retry/stop/escalate decision (3.6).

**What this demonstrates.** An audit answered with "here's what I found and fixed, here's what I
checked and it held, here's the one place a number got worse and I reported it anyway" is worth more
than an audit that just re-reads the invariants back and says they're fine. The self-audit habit this
project has practiced all along — treat your own claims adversarially — is the reason a real,
previously-invisible bug (A36's missing rebaseline) got caught before submission instead of by a
reviewer running `git log` on the config file.

## 25. The policy could decide, but it had never actually done anything

**What happened.** `HANDOFF.md` had carried the same line in its "what's left" list for days: *"the
policy schedules a retry and nothing ever fires it."* Every decision in the live batch was real —
real entities, real compliance checks, real audit records — and every one of them was still only an
*intent*. Nothing downstream of a `retry_scheduled` decision ever caused anything to happen. The
system had a complete decision loop and an empty action loop, and the gap was easy to miss precisely
because everything around it worked.

**What firing a retry actually means here.** Razorpay Payment Links have no native retry primitive.
The first implementation created a second Payment Link — which worked, and four fired that way,
verifiable by id. It got replaced, for a reason that only surfaced by building it: a Payment Link is a
payment intent *plus* a hosted page and a customer-facing URL. An automatic retry doesn't contact the
customer, so modelling one as a customer-facing link overstated what the action was. An **Order** is
the payment-intent primitive on its own — amount, merchant receipt, status — and is the honest match.
The retry now creates an Order carrying the original mandate's id, the attempt number, the rule id
that decided it, and the `scheduled_retry_at` the policy computed, then re-fetches it to confirm it
exists rather than trusting the create response.

**A second bug, found on the way in.** `live_batch.py` computed its compliance checks and then never
read them. Every decision was recorded exactly as the policy proposed, compliant or not — which is
entry 10's "logged but not enforced" bug, reintroduced in the live-integration path years of build-log
discipline later, in the one file where it would have mattered most. It had been harmless only because
nothing acted on decisions; wiring up real execution would have made it a live defect that fired
legally-refusable retries against real amounts. The veto is now shared with `eval/harness.py`,
`_fire_retry_action` is only ever reachable through it, and five regression tests pin the behaviour.

**A platform limit, found by exhausting it.** Firing retries doubled the write volume per case, which
first tripped the rate limiter (pacing raised 1.5s → 4.0s) and then hit something harder: *"test mode
limit of 30 reached for payment_link."* A lifetime cap, not a rate limit — verified by paging the
account and counting exactly 30. That made a create-first batch permanently un-runnable on this
account, which would have made the whole thing undemonstrable on camera.

The fix turned out to be the better design anyway. **A recovery system doesn't create the failed
payment it's recovering — it reacts to one that already exists.** The batch now reads real entities off
the account instead of manufacturing its own subjects, which is both more faithful and idempotent:
re-runnable indefinitely, on whatever the account actually holds. The quota forced a question whose
honest answer was already the right one.

**Verified, both directions.** Below-ceiling amounts fire real Orders — six of them, each confirmed by
independent re-fetch, carrying receipts like `retry-2-plink_TUkx9KUDNPM0zp` and the deciding rule id in
their notes. The ₹41,000 case — above the ₹15,000 no-OTP ceiling (A6) — **escalated and fired exactly
nothing**. That's the veto proven by absence rather than by label: not "we recorded an escalation," but
"no Order exists for that mandate, and you can check."

**What this does not prove, stated plainly.** The Order is created immediately rather than at
`scheduled_retry_at`, because a script can't idle for a T+7 cadence — that gap is recorded in the
record's own metadata, not hidden. And creating a payment intent is not collecting money: completing a
checkout still needs a human (entry 4). This proves the decision reaches the API as a real action. It
does not prove the retry succeeds, and the report says so.

**What it demonstrates.** Closing the last gap between "the system decided" and "the system did," and
finding two real defects in the process — one dormant bug that would have gone live with the feature,
and one platform constraint that could only be discovered by actually consuming it. The discipline that
mattered was refusing to let "it works" stand in for "I checked both branches": the escalation case
firing nothing is the half that's easy to skip and the half that actually proves the compliance floor.

## 26. The regulation had a carve-out. The code had a branch for it. They never once met.

**What happened.** While writing an explainer of the policy — not debugging, just trying to describe
rule ADAPT-002 accurately — the over-ceiling check stopped making sense on a second read:

```python
if state.mandate.amount_type.value in ceiling_cfg["higher_ceiling_categories"]:
```

`amount_type.value` is one of `ott_subscription`, `sip_investment`, `emi`. `higher_ceiling_categories`
is `["insurance", "mutual_funds", "credit_card_bills"]`. The intersection of those two sets is empty,
and always was. A6's higher ₹1,00,000 ceiling could never apply to anything, anywhere, in either the
policy or the compliance invariant.

**Why it was invisible.** There *is* a unit test for the higher ceiling, and it passed the whole time —
because it builds `ProposedDecision(amount_category="mutual_funds")` by hand. It proves the invariant
handles the category correctly and proves nothing whatsoever about whether any real code path ever
supplies that category. Nothing did: `amount_category` defaulted to `"general"` at every production
call site. This is entry 14's lesson arriving a second time in a different costume — a rule that
passes its unit test, runs in production, and does nothing. The first time it was a congestion window
no attempt could ever land in. This time it was a regulatory carve-out no product could ever qualify
for.

**Who it was costing.** A SIP *is* a mutual-fund product — that is what a Systematic Investment Plan
is — so the dead branch was dead for precisely the population it had been written to serve. **12.3% of
all mandates** were SIP mandates above ₹15,000: legally auto-retryable up to ₹1,00,000, and escalated
anyway. Not a compliance violation — escalating when you may retry is over-cautious, not illegal — but
a straight recovery loss, and a misimplementation of a documented FACT rather than a judgement call.

**The fix.** A single `RBI_CATEGORY_BY_AMOUNT_TYPE` mapping in `compliance/`, next to the rest of the
regulatory knowledge so the policy and the invariant cannot drift apart on it, plus threading
`amount_category` through the harness at the point the `ProposedDecision` is built. Deliberately
partial: `sip_investment → mutual_funds` and nothing else. `emi` is **not** mapped to
`credit_card_bills` — an EMI is a loan instalment and a credit-card bill is a different instrument, and
guessing an extra category into a regulatory carve-out claims a legal allowance with no citation
behind it. That is exactly the mistake A4 represented, and it is not worth repeating for a few points
of recovery.

**What it did to the numbers, including the part that hurts.**

| | before | after |
|---|---|---|
| baseline recovery | 56.9% | **65.9%** |
| baseline non-compliant proposals | 22.8% | **11.7%** |
| adaptive recovery | 78.0% | **86.0%** |
| adaptive value recovered | ₹21.3M | **₹30.1M** |
| lift from compliance awareness alone | +12.0% | **+5.3%** |
| lift from retry timing alone | +22.4% | **+23.9%** |
| **conservative headline** | **+12.5%** | **+8.7%** |

The headline fell by roughly a third, and the reason is worth stating precisely: **the bug was
handicapping the baseline more than it was handicapping us.** Half the baseline's blocked proposals
were legal all along. Our own compliance implementation had been manufacturing lift by refusing
retries the law permits — which is entry 13's finding almost exactly, arriving from the opposite
direction. Entry 13 found an accidentally weak baseline in the *config*. This one was in the
*compliance layer*, which is worse, because that is the layer the project points at when it argues it
should be trusted.

**The consolation is real, and it is not the number.** The decomposition got materially more
defensible: compliance awareness now accounts for +5.3% of the recovery gain instead of +12.0%, and
timing for +23.9%. Before this fix, the largest single driver of the value headline was a
compliance freebie. Now the majority of what remains is the part actually engineered. A smaller
number, carrying a much better claim.

**What now guards it.** `tests/test_otp_ceiling_categories.py` tests *reachability*, which is the
property that was missing: at least one `AmountType` must map into a higher-ceiling category, every
mapped category must be one the config actually names, unmapped products must fall back to `general`,
and the end-to-end behaviour is pinned in both directions — a ₹20,000 SIP passes, a ₹20,000 EMI is
still blocked. Verified to fail against the pre-fix state rather than assumed to.

**What it demonstrates.** That "it has a test" and "it works" are different claims, and the gap
between them is where this project keeps finding its own bugs — twice now by the same mechanism. Also
that the discipline holds under pressure: this surfaced nine days before submission, while writing
*promotional* material, and it cost a third of the headline number. Reporting +8.7% because it is true
is the entire argument for believing anything else here.

## 27. Writing the benchmark found the bug in the benchmark

**What happened.** `HANDOFF.md` claimed **65,268 decisions/sec, "measured, not estimated."** There was
no benchmark anywhere in the repository. The number may well have been measured once, in a terminal,
by a person who then closed the terminal — but in a project whose whole argument is *re-run everything
yourself*, a number nobody else can reproduce is worse than no number at all. It was also the single
most falsifiable claim in the submission, in exchange for an assertion nobody was disputing: yes, a
rules engine is fast.

**The interesting part is not the benchmark.** It is what happened when a test was written to check
the benchmark was measuring the right thing.

`build_states` generated inputs by indexing three lists with the loop counter: six amounts, three
product types, six failure classes. Those lengths share factors, so the three axes never varied
independently — the ₹41,000 EMI case, the *only* combination that should reach the over-ceiling
escalation branch, always landed on the same failure class. That class happened to be unrecoverable,
and rule ADAPT-001 short-circuits unrecoverable failures before the ceiling check ever runs.

**So the escalation branch was never executed, and the benchmark was timing only the cheap paths.** It
would have reported a number that was too high, forever, and nothing about it would have looked wrong.
A performance claim can become a lie without anyone editing it.

`tests/test_benchmark_fidelity.py` caught it on the first run, because it asserts a property rather
than a value: the benchmark must produce at least three distinct decision types. It produced two.
Fixed by building states from the explicit cartesian product, deterministically shuffled so that a
prefix of any length stays representative — the second version of the same bug, caught by the same
test, when product ordering meant a short run only saw small amounts.

**A third thing, fixed on the way.** The benchmark needed the veto, which by then existed in two
places: inline in `eval/harness.py` and as `apply_compliance_veto` in the live batch. Adding a third
copy to time it would have been the worst possible version — a benchmark measuring a code path that
resembles production rather than being it. The veto moved into `compliance/invariants/rules.py`, where
enforcement belongs, and all three callers now share one function. Given this exact wiring has been
got wrong twice already (entry 10 executed non-compliant retries; entry 25 never read the verdicts),
having one implementation instead of three is worth more than the benchmark that prompted it.

**The honest number.** ~133,000 decisions/sec median on Apple Silicon under CPython 3.14, roughly
7.5µs per decision, compliance checks included — reproducible via `python -m eval.benchmark`, which
prints the machine alongside the figure because a throughput number without hardware is not a claim.
It is *higher* than the 65,268 it replaces, which is its own small lesson: the unreproducible number
was not being generous to itself, it simply could not be checked in either direction.

**What it demonstrates.** That the fastest way to find out whether a measurement is meaningful is to
try to test it. Also the narrower engineering point: benchmarks are code, they carry bugs like code,
and the bugs are unusually dangerous because the output is a plausible number rather than a crash. The
property worth asserting was never "is it fast" — it was "is it measuring all of the thing."
