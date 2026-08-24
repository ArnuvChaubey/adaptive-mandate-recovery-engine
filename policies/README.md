# policies/

The shared contract every policy implements: `decide(state, failure_event) -> Decision{retry_at | escalate_action}`.
This is what makes "policy-agnostic evaluation harness" an architectural fact rather than a marketing sentence.

Planned (Milestone 3, Day 5-6):
- `policy_interface/` — the contract itself.
- `baseline_policy/` — documented halt condition (4 attempts) + conservatively-biased assumed cadence (A1).
- `adaptive_policy/` — deterministic, context-aware reference implementation. The LLM is never in this
  decision loop — see `narrator/` and `docs/positioning.md`.
- `external_policy_stub/` — deliberately unreachable "third slot" (A26): proves the interface generalizes,
  documented as unimplemented-by-design since no real external engine (e.g. Razorpay's own Intelligent Retry
  Engine) exposes a callable API. An honest limitation, shown rather than implied away.
