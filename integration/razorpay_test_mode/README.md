# integration/razorpay_test_mode/

The scripted, repeatable seed process against real Razorpay test-mode APIs. This is a **qualitative
integration proof** — evidence the system calls real APIs end to end — not a statistically powered validation
set. At the scale available (~15-20 live cases), it cannot carry the recovery-rate or lift claim; that claim
rests entirely on `simulator/` and `eval/`. See A30 and `docs/positioning.md`.

## What actually expires

API keys (`rzp_test_...` plus the secret) are **permanent** — they do not expire and need no
rotation. What expires is a **card token**, created when a customer authorises a subscription
mandate: those are valid for 3 days in test mode, which is the real content of A29.

Because the live subset uses one-time Payment Links (see the Day 2 finding below), which tokenise
nothing, the 3-day window does not currently constrain when M6 can run.

Day 1: SDK client wired to `.env` test-mode credentials, no live calls yet.
Day 2: webhook receiver behind a public tunnel (ngrok), first real end-to-end webhook received and logged
into the same `audit/` schema as the simulator, tagged `source: live_test_mode`.
Milestone 6 (Day 10): full ~15-20 case scripted batch run, timed close to the video-recording date to respect
the 3-day test-mode token window (A29).

## Day 2 finding: subscription card tokenization failed server-side in test mode

Multiple attempts to authenticate a test Subscription's card (via the hosted `short_url` checkout) failed
with a generic "Payment could not be completed" message. The webhook log later confirmed these were real,
signed `payment.failed` events from Razorpay's backend, every one carrying
`"error_step": "card_mandate_process", "error_reason": "server_error"` -- a genuine platform-side failure in
the RBI CoFT card-tokenization step during test mode, not a client-side mistake. Razorpay's own
`subscriptions/test-guide` documentation describes a simpler Pay -> Success flow with no OTP step at all,
which no longer matches current product behavior -- likely documentation lag behind a tightened tokenization
requirement.

**Workaround:** `create_test_payment_link.py` creates a plain one-time Payment Link instead of authenticating
a Subscription. One-time payments don't require card tokenization, so they route through the simple mock
bank Success/Failure page and produce a real `payment.authorized` / `payment.captured` pair -- sufficient to
prove the tunnel + signature verification + audit logging mechanism end to end.

**Confirmed persistent, not a one-off.** Retried deliberately two days later, fresh subscription, clean
browser profile, same documented test card -- same failure. Two independent occurrences on different dates
is the signature of a real platform issue rather than a transient blip. Full subscription-lifecycle
authentication (`create_test_subscription.py`) is out of scope for this submission on that basis, not
because it was undertried. See `docs/build_log.md` entries 4 and 23.
