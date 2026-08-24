# Positioning

## The pitch, precisely

Razorpay's own **Intelligent Retry Engine** (part of the "Intelligent Revenue-Protect" stack, announced in beta
at FTX 2026) already validates this project's core thesis: fixed-interval retry is the wrong model for recurring
payment recovery. Their own materials describe traditional retry systems as "rigid" and retrying "at fixed
intervals without understanding user context, bank availability, or merchant priorities."

What they do not publish: any decision methodology, whether the engine is rule-based or ML-driven, any
recovery-rate or lift numbers, or anything resembling an audit trail. It ships as a configurable black box with a
merchant-facing template UI.

**This project is not a claim to have invented adaptive retry.** It is an open, auditable, reproducible
evaluation harness for adaptive mandate-recovery policies — the credibility layer that a system like the
Intelligent Retry Engine does not currently expose publicly. The Adaptive Policy Engine shipped here is one
example policy plugged into that harness through a policy-agnostic interface (`policies/policy_interface/`),
not the headline deliverable itself.

Sources: [Razorpay Newsroom, FTX 2026](https://razorpay.com/newsroom/razorpay-launches-the-worlds-first-ai-native-agent-studio-for-payments-at-ftx26-powered-by-anthropics-claude/),
[Intelligent Revenue-Protect blog](https://razorpay.com/blog/upi-autopay-with-intelligent-revenue-protect/).

## What this directly answers in Track 03's judging criteria

- **AI judgment** ("the right tool in the right place, and where you chose not to use one") — the deterministic
  policy engine makes every retry/stop/escalate decision; the LLM is confined to `narrator/`, reading the
  decision log after the fact and never writing back into policy state. See `audit/decision_log_schema/`.
- **Build quality** ("would you trust it") — every simulator parameter that isn't directly sourced is tagged
  with an assumption ID and a confidence level in `assumptions.md`; nothing is asserted as fact that isn't.

## Honest limits of this positioning (do not overstate in the pitch video)

- The harness's "policy-agnostic" property is a design fact, not something demonstrated against Razorpay's
  actual engine — neither the Intelligent Retry Engine nor the Subscription Recovery Agent exposes a public
  callable interface. See A26 in `assumptions.md`. `policies/external_policy_stub/` exists to make this
  limitation visible in the architecture rather than implying it away.
- "No independent public benchmark exists" (A25) is scoped narrowly to *public* — Razorpay may well have
  internal benchmarks they simply don't publish. Never claim more than the narrow version.
