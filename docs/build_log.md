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
