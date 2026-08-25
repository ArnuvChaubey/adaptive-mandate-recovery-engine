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
